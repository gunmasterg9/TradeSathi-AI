/**
 * TradeSathi AI — Resilient API Client Helper
 * Safely handles fetch responses, prevents "Unexpected end of JSON input" errors
 * on empty or non-JSON responses, and preserves full HTTP status and detail codes.
 */

export const API_BASE = (
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE_URL) ||
  (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE_URL) ||
  ''
).replace(/\/$/, '')

/**
 * Safely parse a fetch Response object without crashing on empty bodies or non-JSON content.
 *
 * @param {Response} response - The fetch Response object
 * @param {string} defaultErrorMsg - Default fallback message for errors
 * @returns {Promise<any>} - Parsed JSON object, text, or null if body is empty
 * @throws {Error} - Formatted Error with HTTP status code and error details if !response.ok
 */
export async function parseApiResponse(response, defaultErrorMsg = 'Request failed') {
  const status = response.status
  const statusText = response.statusText || ''
  const contentType = (response.headers.get('content-type') || '').toLowerCase()
  const isJson = contentType.includes('application/json')

  let rawText = ''
  try {
    rawText = await response.text()
  } catch {
    rawText = ''
  }

  const isEmpty = !rawText || !rawText.trim()
  let jsonData = null

  if (isJson && !isEmpty) {
    try {
      jsonData = JSON.parse(rawText)
    } catch {
      jsonData = null
    }
  }

  // Handle non-2xx HTTP responses
  if (!response.ok) {
    let detail = ''
    if (jsonData && typeof jsonData === 'object') {
      detail = jsonData.detail || jsonData.message || jsonData.error || ''
      if (typeof detail === 'object') {
        detail = JSON.stringify(detail)
      }
    } else if (!isEmpty) {
      // Strip HTML tags if error is an HTML error page (e.g. from a reverse proxy or server crash)
      const clean = rawText.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
      detail = clean.length > 250 ? clean.slice(0, 250) + '...' : clean
    }

    if (!detail && (status === 502 || status === 504)) {
      detail =
        'TradeSathi API backend is unreachable. Verify that the FastAPI server is running on the configured port.'
    }

    const statusBadge = `HTTP ${status}${statusText ? ` ${statusText}` : ''}`
    const fullMessage = detail
      ? `${statusBadge}: ${detail}`
      : `${statusBadge} (${defaultErrorMsg})`

    const error = new Error(fullMessage)
    error.status = status
    error.statusText = statusText
    error.detail = detail
    error.data = jsonData
    throw error
  }

  // Handle 2xx HTTP response with empty body (e.g. 204 No Content or empty 200)
  if (isEmpty) {
    return null
  }

  // Handle 2xx HTTP response with valid JSON
  if (jsonData !== null) {
    return jsonData
  }

  // Fallback for 2xx with non-JSON plain text
  return rawText
}

/**
 * Resilient API fetch wrapper.
 * Automatically prepends API_BASE and parses responses safely.
 *
 * NOTE: Mutating requests (POST, PATCH, DELETE) are NEVER retried automatically
 * to prevent duplicate audit creations or unintended database side-effects.
 *
 * @param {string} endpoint - API path (e.g. '/api/samples') or full URL
 * @param {RequestInit} [options={}] - Standard fetch options
 * @param {string} [defaultErrorMsg='Request failed'] - Contextual fallback error message
 * @returns {Promise<any>}
 */
export async function apiFetch(endpoint, options = {}, defaultErrorMsg = 'Request failed') {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`
  let response
  try {
    response = await fetch(url, options)
  } catch (networkErr) {
    // Distinguish offline / connection refused from response parsing errors
    const err = new Error(
      `Network Error: Cannot connect to TradeSathi API backend at "${url}". Check that the FastAPI server is running.`
    )
    err.originalError = networkErr
    throw err
  }

  return parseApiResponse(response, defaultErrorMsg)
}
