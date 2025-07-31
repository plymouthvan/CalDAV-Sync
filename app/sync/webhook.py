"""
Webhook delivery system for CalDAV Sync Microservice.

Handles webhook delivery after sync operations with retry logic
and non-blocking operation to avoid impacting sync performance.
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import httpx
import pytz

from app.database import CalendarMapping, SyncLog, WebhookRetry, get_db
from app.config import get_settings
from app.utils.logging import WebhookLogger
from app.utils.exceptions import WebhookDeliveryError, WebhookTimeoutError


class WebhookPayload:
    """Represents a webhook payload to be sent."""
    
    def __init__(self, mapping: CalendarMapping, sync_log: SyncLog, events: List[Dict[str, Any]] = None):
        self.mapping = mapping
        self.sync_log = sync_log
        self.events = events or []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert payload to dictionary format."""
        return {
            "mapping_id": self.mapping.id,
            "direction": self.sync_log.direction,
            "status": self.sync_log.status,
            "timestamp": self.sync_log.completed_at.isoformat() if self.sync_log.completed_at else datetime.utcnow().isoformat(),
            "inserted": self.sync_log.inserted_count,
            "updated": self.sync_log.updated_count,
            "deleted": self.sync_log.deleted_count,
            "events": self.events
        }


class WebhookClient:
    """Handles webhook delivery with retry logic."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def send_webhook(self, webhook_url: str, payload: Dict[str, Any], 
                          mapping_id: str, timeout: Optional[int] = None) -> bool:
        """
        Send webhook payload to the specified URL.
        
        Args:
            webhook_url: URL to send webhook to
            payload: Webhook payload dictionary
            mapping_id: Calendar mapping ID for logging
            timeout: Request timeout in seconds
            
        Returns:
            True if successful, False otherwise
        """
        logger = WebhookLogger(mapping_id, webhook_url)
        
        if timeout is None:
            timeout = self.settings.webhooks.timeout_seconds
        
        try:
            start_time = datetime.utcnow()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    timeout=timeout,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "CalDAV-Sync-Microservice/1.0"
                    }
                )
                
                end_time = datetime.utcnow()
                # Ensure timezone awareness for subtraction
                if end_time.tzinfo is None:
                    end_time = pytz.UTC.localize(end_time)
                if start_time.tzinfo is None:
                    start_time = pytz.UTC.localize(start_time)
                response_time = (end_time - start_time).total_seconds()
                
                # Consider 2xx status codes as success
                if 200 <= response.status_code < 300:
                    logger.log_webhook_sent(response.status_code, response_time)
                    return True
                else:
                    logger.log_webhook_failed(
                        f"HTTP {response.status_code}: {response.text[:200]}",
                        response.status_code
                    )
                    return False
        
        except httpx.TimeoutException:
            logger.log_webhook_failed(f"Request timeout after {timeout}s")
            return False
        
        except httpx.RequestError as e:
            logger.log_webhook_failed(f"Request error: {str(e)}")
            return False
        
        except Exception as e:
            logger.log_webhook_failed(f"Unexpected error: {str(e)}")
            return False
    
    async def send_sync_result_webhook(self, mapping: CalendarMapping, sync_log: SyncLog, 
                                     events: List[Dict[str, Any]] = None) -> bool:
        """
        Send webhook for sync result.
        
        Args:
            mapping: Calendar mapping configuration
            sync_log: Sync log record
            events: Optional list of event details
            
        Returns:
            True if successful or no webhook configured, False if failed
        """
        if not mapping.webhook_url:
            return True  # No webhook configured, consider success
        
        # Create payload
        webhook_payload = WebhookPayload(mapping, sync_log, events)
        payload_dict = webhook_payload.to_dict()
        
        # Filter events if not including details
        if not self.settings.webhooks.include_event_details:
            payload_dict.pop("events", None)
        
        # Send webhook
        success = await self.send_webhook(
            mapping.webhook_url,
            payload_dict,
            mapping.id
        )
        
        # Update sync log with webhook status
        with next(get_db()) as db:
            sync_log.webhook_sent = True
            sync_log.webhook_status = "success" if success else "failure"
            db.commit()
        
        # Queue retry if failed
        if not success:
            await self.queue_webhook_retry(mapping, sync_log, payload_dict)
        
        return success
    
    async def queue_webhook_retry(self, mapping: CalendarMapping, sync_log: SyncLog, 
                                payload: Dict[str, Any], attempt: int = 0) -> bool:
        """
        Queue webhook for retry.
        
        Args:
            mapping: Calendar mapping configuration
            sync_log: Sync log record
            payload: Webhook payload
            attempt: Current attempt number (0-based)
            
        Returns:
            True if queued successfully, False if max attempts reached
        """
        if attempt >= self.settings.webhooks.max_retries:
            return False
        
        # Calculate next retry time
        delay_seconds = self.settings.webhooks.retry_delays[min(attempt, len(self.settings.webhooks.retry_delays) - 1)]
        next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        
        # Create retry record
        retry_record = WebhookRetry(
            sync_log_id=sync_log.id,
            webhook_url=mapping.webhook_url,
            payload=json.dumps(payload),
            attempt_count=attempt,
            max_attempts=self.settings.webhooks.max_retries,
            next_retry_at=next_retry_at
        )
        
        # Save to database
        with next(get_db()) as db:
            db.add(retry_record)
            db.commit()
        
        # Log retry scheduling
        logger = WebhookLogger(mapping.id, mapping.webhook_url)
        logger.log_webhook_retry(attempt + 1, next_retry_at)
        
        return True
    
    async def process_webhook_retries(self) -> int:
        """
        Process pending webhook retries.
        
        Returns:
            Number of retries processed
        """
        processed_count = 0
        
        with next(get_db()) as db:
            # Get retries that are due
            now = datetime.utcnow()
            pending_retries = db.query(WebhookRetry).filter(
                WebhookRetry.next_retry_at <= now,
                WebhookRetry.attempt_count < WebhookRetry.max_attempts
            ).all()
            
            for retry in pending_retries:
                try:
                    # Parse payload
                    payload = json.loads(retry.payload)
                    
                    # Attempt delivery
                    success = await self.send_webhook(
                        retry.webhook_url,
                        payload,
                        payload.get("mapping_id", "unknown"),
                        timeout=self.settings.webhooks.timeout_seconds
                    )
                    
                    if success:
                        # Remove successful retry
                        db.delete(retry)
                        processed_count += 1
                    else:
                        # Update retry record
                        retry.attempt_count += 1
                        retry.last_error = f"Retry attempt {retry.attempt_count} failed"
                        
                        if retry.attempt_count < retry.max_attempts:
                            # Schedule next retry
                            delay_index = min(retry.attempt_count, len(self.settings.webhooks.retry_delays) - 1)
                            delay_seconds = self.settings.webhooks.retry_delays[delay_index]
                            retry.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
                        else:
                            # Max attempts reached, mark as failed
                            retry.last_error = f"Max retry attempts ({retry.max_attempts}) reached"
                        
                        retry.updated_at = datetime.utcnow()
                
                except Exception as e:
                    # Update retry record with error
                    retry.attempt_count += 1
                    retry.last_error = f"Retry processing error: {str(e)}"
                    retry.updated_at = datetime.utcnow()
            
            db.commit()
        
        return processed_count
    
    async def cleanup_old_retries(self, days_old: int = 7) -> int:
        """
        Clean up old webhook retry records.
        
        Args:
            days_old: Remove retries older than this many days
            
        Returns:
            Number of records cleaned up
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        with next(get_db()) as db:
            # Remove old failed retries
            old_retries = db.query(WebhookRetry).filter(
                WebhookRetry.created_at < cutoff_date,
                WebhookRetry.attempt_count >= WebhookRetry.max_attempts
            )
            
            count = old_retries.count()
            old_retries.delete()
            db.commit()
        
        return count
    
    def get_retry_stats(self) -> Dict[str, Any]:
        """
        Get statistics about webhook retries.
        
        Returns:
            Dictionary with retry statistics
        """
        with next(get_db()) as db:
            total_retries = db.query(WebhookRetry).count()
            pending_retries = db.query(WebhookRetry).filter(
                WebhookRetry.attempt_count < WebhookRetry.max_attempts
            ).count()
            failed_retries = db.query(WebhookRetry).filter(
                WebhookRetry.attempt_count >= WebhookRetry.max_attempts
            ).count()
            
            # Get next retry time
            next_retry = db.query(WebhookRetry).filter(
                WebhookRetry.attempt_count < WebhookRetry.max_attempts
            ).order_by(WebhookRetry.next_retry_at).first()
            
            return {
                "total_retries": total_retries,
                "pending_retries": pending_retries,
                "failed_retries": failed_retries,
                "next_retry_at": next_retry.next_retry_at.isoformat() if next_retry else None
            }


class WebhookRetryProcessor:
    """Background processor for webhook retries."""
    
    def __init__(self):
        self.webhook_client = WebhookClient()
        self.running = False
        self.task = None
    
    async def start(self):
        """Start the retry processor."""
        if self.running:
            return
        
        self.running = True
        self.task = asyncio.create_task(self._process_loop())
    
    async def stop(self):
        """Stop the retry processor."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
    
    async def _process_loop(self):
        """Main processing loop for webhook retries."""
        while self.running:
            try:
                # Process pending retries
                processed = await self.webhook_client.process_webhook_retries()
                
                if processed > 0:
                    print(f"Processed {processed} webhook retries")
                
                # Clean up old retries periodically
                if datetime.utcnow().minute == 0:  # Once per hour
                    cleaned = await self.webhook_client.cleanup_old_retries()
                    if cleaned > 0:
                        print(f"Cleaned up {cleaned} old webhook retries")
                
                # Wait before next check
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in webhook retry processor: {e}")
                await asyncio.sleep(60)


# Global instances
webhook_client = WebhookClient()
webhook_retry_processor = WebhookRetryProcessor()


def get_webhook_client() -> WebhookClient:
    """Get the global webhook client instance."""
    return webhook_client


def get_webhook_retry_processor() -> WebhookRetryProcessor:
    """Get the global webhook retry processor instance."""
    return webhook_retry_processor
