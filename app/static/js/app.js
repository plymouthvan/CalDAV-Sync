/**
 * CalDAV Sync Microservice - Main JavaScript Application
 * 
 * Provides common functionality for the web UI including API calls,
 * form handling, and utility functions.
 */

// Global configuration
const API_BASE_URL = '/api';
const REFRESH_INTERVAL = 30000; // 30 seconds

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

/**
 * Initialize the application
 */
function initializeApp() {
    // Initialize tooltips
    initializeTooltips();
    
    // Initialize form validation
    initializeFormValidation();
    
    // Initialize auto-refresh for certain pages
    initializeAutoRefresh();
    
    // Initialize keyboard shortcuts
    initializeKeyboardShortcuts();
    
    console.log('CalDAV Sync Microservice UI initialized');
}

/**
 * Initialize Bootstrap tooltips
 */
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * Initialize form validation
 */
function initializeFormValidation() {
    // Add Bootstrap validation classes
    const forms = document.querySelectorAll('.needs-validation');
    
    Array.prototype.slice.call(forms).forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            
            form.classList.add('was-validated');
        }, false);
    });
}

/**
 * Initialize auto-refresh for dashboard and status pages
 */
function initializeAutoRefresh() {
    const currentPath = window.location.pathname;
    
    if (currentPath === '/' || currentPath.includes('status') || currentPath.includes('sync')) {
        // Auto-refresh is handled by individual page scripts
        console.log('Auto-refresh enabled for current page');
    }
}

/**
 * Initialize keyboard shortcuts
 */
function initializeKeyboardShortcuts() {
    document.addEventListener('keydown', function(event) {
        // Ctrl/Cmd + R: Refresh current page data
        if ((event.ctrlKey || event.metaKey) && event.key === 'r') {
            event.preventDefault();
            refreshCurrentPage();
        }
        
        // Ctrl/Cmd + S: Trigger manual sync (if on dashboard)
        if ((event.ctrlKey || event.metaKey) && event.key === 's') {
            if (window.location.pathname === '/') {
                event.preventDefault();
                if (typeof triggerManualSync === 'function') {
                    triggerManualSync();
                }
            }
        }
    });
}

/**
 * API Helper Functions
 */
const API = {
    /**
     * Make a GET request to the API
     */
    async get(endpoint, params = {}) {
        const url = new URL(`${API_BASE_URL}${endpoint}`, window.location.origin);
        Object.keys(params).forEach(key => url.searchParams.append(key, params[key]));
        
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.status} ${response.statusText}`);
        }
        
        return await response.json();
    },
    
    /**
     * Make a POST request to the API
     */
    async post(endpoint, data = {}) {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `API Error: ${response.status} ${response.statusText}`);
        }
        
        return await response.json();
    },
    
    /**
     * Make a PUT request to the API
     */
    async put(endpoint, data = {}) {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `API Error: ${response.status} ${response.statusText}`);
        }
        
        return await response.json();
    },
    
    /**
     * Make a DELETE request to the API
     */
    async delete(endpoint) {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `API Error: ${response.status} ${response.statusText}`);
        }
        
        // DELETE requests might not return JSON
        if (response.status === 204) {
            return {};
        }
        
        return await response.json();
    }
};

/**
 * Utility Functions
 */
const Utils = {
    /**
     * Format a date for display
     */
    formatDate(dateString, options = {}) {
        if (!dateString) return 'Never';
        
        const date = new Date(dateString);
        const defaultOptions = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        };
        
        return date.toLocaleDateString('en-US', { ...defaultOptions, ...options });
    },
    
    /**
     * Format a duration in seconds to human readable format
     */
    formatDuration(seconds) {
        if (!seconds || seconds < 1) return '< 1s';
        
        if (seconds < 60) {
            return `${Math.round(seconds)}s`;
        } else if (seconds < 3600) {
            return `${Math.round(seconds / 60)}m`;
        } else {
            return `${Math.round(seconds / 3600)}h`;
        }
    },
    
    /**
     * Get status badge HTML
     */
    getStatusBadge(status) {
        const badges = {
            'success': '<span class="badge bg-success">Success</span>',
            'failure': '<span class="badge bg-danger">Failed</span>',
            'partial_failure': '<span class="badge bg-warning">Partial</span>',
            'running': '<span class="badge bg-info">Running</span>',
            'enabled': '<span class="badge bg-success">Enabled</span>',
            'disabled': '<span class="badge bg-secondary">Disabled</span>'
        };
        
        return badges[status] || `<span class="badge bg-secondary">${status}</span>`;
    },
    
    /**
     * Get sync direction display text
     */
    getSyncDirectionText(direction) {
        const directions = {
            'caldav_to_google': 'CalDAV → Google',
            'google_to_caldav': 'Google → CalDAV',
            'bidirectional': 'Bidirectional'
        };
        
        return directions[direction] || direction;
    },
    
    /**
     * Debounce function calls
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    /**
     * Copy text to clipboard
     */
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            showAlert('Copied to clipboard', 'success');
        } catch (err) {
            console.error('Failed to copy to clipboard:', err);
            showAlert('Failed to copy to clipboard', 'error');
        }
    },
    
    /**
     * Download data as JSON file
     */
    downloadJSON(data, filename) {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
};

/**
 * Show alert message
 */
function showAlert(message, type = 'info', duration = 5000) {
    const alertId = 'alert-' + Date.now();
    const alertHtml = `
        <div id="${alertId}" class="alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    const container = document.querySelector('main.container');
    if (container) {
        container.insertAdjacentHTML('afterbegin', alertHtml);
        
        // Auto-dismiss after specified duration
        setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                alert.remove();
            }
        }, duration);
    }
}

/**
 * Show loading spinner
 */
function showLoading(element, text = 'Loading...') {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.innerHTML = `
            <div class="text-center">
                <div class="spinner-border" role="status">
                    <span class="visually-hidden">${text}</span>
                </div>
                <div class="mt-2">${text}</div>
            </div>
        `;
    }
}

/**
 * Hide loading spinner and show content
 */
function hideLoading(element, content = '') {
    if (typeof element === 'string') {
        element = document.getElementById(element);
    }
    
    if (element) {
        element.innerHTML = content;
    }
}

/**
 * Refresh current page data
 */
function refreshCurrentPage() {
    const currentPath = window.location.pathname;
    
    // Call page-specific refresh functions if they exist
    if (typeof loadDashboardData === 'function' && currentPath === '/') {
        loadDashboardData();
        showAlert('Dashboard refreshed', 'info');
    } else if (typeof loadPageData === 'function') {
        loadPageData();
        showAlert('Page refreshed', 'info');
    } else {
        // Fallback: reload the page
        window.location.reload();
    }
}

/**
 * Confirm action with user
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

/**
 * Format file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Validate email address
 */
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

/**
 * Validate URL
 */
function isValidURL(url) {
    try {
        new URL(url);
        return true;
    } catch {
        return false;
    }
}

/**
 * Handle form submission with loading state
 */
async function handleFormSubmit(form, submitHandler) {
    const submitButton = form.querySelector('button[type="submit"]');
    const originalText = submitButton.textContent;
    
    try {
        // Show loading state
        submitButton.disabled = true;
        submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        
        // Call the submit handler
        await submitHandler(new FormData(form));
        
        showAlert('Saved successfully', 'success');
        
    } catch (error) {
        console.error('Form submission error:', error);
        showAlert(error.message || 'An error occurred', 'error');
        
    } finally {
        // Restore button state
        submitButton.disabled = false;
        submitButton.textContent = originalText;
    }
}

/**
 * Auto-save form data to localStorage
 */
function enableAutoSave(formId, key) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    // Load saved data
    const savedData = localStorage.getItem(key);
    if (savedData) {
        try {
            const data = JSON.parse(savedData);
            Object.keys(data).forEach(fieldName => {
                const field = form.querySelector(`[name="${fieldName}"]`);
                if (field) {
                    field.value = data[fieldName];
                }
            });
        } catch (error) {
            console.error('Error loading saved form data:', error);
        }
    }
    
    // Save data on input
    const saveData = Utils.debounce(() => {
        const formData = new FormData(form);
        const data = {};
        for (const [key, value] of formData.entries()) {
            data[key] = value;
        }
        localStorage.setItem(key, JSON.stringify(data));
    }, 1000);
    
    form.addEventListener('input', saveData);
    form.addEventListener('change', saveData);
    
    // Clear saved data on successful submit
    form.addEventListener('submit', () => {
        setTimeout(() => {
            localStorage.removeItem(key);
        }, 1000);
    });
}

/**
 * Smart polling for sync completion
 */
async function pollForSyncCompletion(triggeredMappingIds, options = {}) {
    const {
        maxAttempts = 20,
        pollInterval = 500,
        onProgress = null,
        onComplete = null,
        onError = null
    } = options;
    
    let attempts = 0;
    
    const poll = async () => {
        attempts++;
        
        try {
            const response = await API.get('/sync/active');
            const currentActiveSyncs = new Set(response.active_mapping_ids);
            
            // Check if any of our triggered syncs are still running
            const ourActiveSyncs = triggeredMappingIds.filter(id => currentActiveSyncs.has(id));
            const completed = triggeredMappingIds.length - ourActiveSyncs.length;
            
            // Call progress callback if provided
            if (onProgress) {
                onProgress(completed, triggeredMappingIds.length, ourActiveSyncs);
            }
            
            if (ourActiveSyncs.length === 0) {
                // All syncs complete
                if (onComplete) {
                    onComplete();
                }
                return;
            }
            
            // Continue polling if we haven't exceeded max attempts
            if (attempts < maxAttempts) {
                setTimeout(poll, pollInterval);
            } else {
                // Timeout reached
                if (onError) {
                    onError(new Error('Polling timeout reached'));
                }
            }
            
        } catch (error) {
            console.error('Polling error:', error);
            
            // Retry a few times on error
            if (attempts < 3) {
                setTimeout(poll, pollInterval * 2);
            } else {
                if (onError) {
                    onError(error);
                }
            }
        }
    };
    
    // Start polling after a brief delay
    setTimeout(poll, 200);
}

/**
 * Enhanced trigger sync with smart polling
 */
async function triggerSyncWithPolling(mappingIds = null) {
    try {
        const requestBody = mappingIds ? { mapping_ids: mappingIds } : {};
        const response = await API.post('/sync/trigger', requestBody);
        
        if (response.triggered_count > 0 && response.triggered_mapping_ids) {
            return new Promise((resolve, reject) => {
                pollForSyncCompletion(response.triggered_mapping_ids, {
                    onComplete: () => {
                        showAlert(`Sync completed for ${response.triggered_count} mappings`, 'success');
                        resolve(response);
                    },
                    onError: (error) => {
                        showAlert('Sync polling failed - please refresh manually', 'warning');
                        resolve(response); // Still resolve, just with warning
                    }
                });
            });
        } else {
            showAlert(response.message || 'No syncs were triggered', 'info');
            return response;
        }
        
    } catch (error) {
        showAlert(error.message || 'Failed to trigger sync', 'error');
        throw error;
    }
}

// Export functions for use in other scripts
window.CalDAVSync = {
    API,
    Utils,
    showAlert,
    showLoading,
    hideLoading,
    refreshCurrentPage,
    confirmAction,
    handleFormSubmit,
    enableAutoSave,
    pollForSyncCompletion,
    triggerSyncWithPolling
};
