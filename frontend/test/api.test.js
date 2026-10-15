import test from 'node:test'
import assert from 'node:assert/strict'
import { parseApiResponse } from '../src/api.js'

test('parseApiResponse: parses successful JSON response cleanly', async () => {
  const mockResponse = new Response(JSON.stringify({ status: 'ok', id: 'anl-123' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
  const result = await parseApiResponse(mockResponse)
  assert.deepEqual(result, { status: 'ok', id: 'anl-123' })
})

test('parseApiResponse: handles empty 200 response body without JSON crash', async () => {
  const mockResponse = new Response('', {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
  const result = await parseApiResponse(mockResponse)
  assert.equal(result, null)
})

test('parseApiResponse: handles 204 No Content with empty body', async () => {
  const mockResponse = new Response(null, {
    status: 204,
  })
  const result = await parseApiResponse(mockResponse)
  assert.equal(result, null)
})

test('parseApiResponse: extracts detail from JSON error response', async () => {
  const mockResponse = new Response(JSON.stringify({ detail: 'Upload at least one document.' }), {
    status: 400,
    statusText: 'Bad Request',
    headers: { 'Content-Type': 'application/json' },
  })
  await assert.rejects(
    async () => {
      await parseApiResponse(mockResponse)
    },
    (err) => {
      assert.match(err.message, /HTTP 400 Bad Request: Upload at least one document\./)
      assert.equal(err.status, 400)
      return true
    }
  )
})

test('parseApiResponse: handles non-JSON HTML/text error response without JSON crash', async () => {
  const htmlError = '<html><body><h1>504 Gateway Timeout</h1><p>Connection refused</p></body></html>'
  const mockResponse = new Response(htmlError, {
    status: 504,
    statusText: 'Gateway Timeout',
    headers: { 'Content-Type': 'text/html' },
  })
  await assert.rejects(
    async () => {
      await parseApiResponse(mockResponse)
    },
    (err) => {
      assert.match(err.message, /HTTP 504 Gateway Timeout/)
      assert.match(err.message, /Connection refused/)
      // Must NOT be the cryptic SyntaxError: Unexpected end of JSON input
      assert.doesNotMatch(err.message, /Unexpected end of JSON input/)
      assert.doesNotMatch(err.message, /Failed to execute 'json'/)
      return true
    }
  )
})

test('parseApiResponse: handles empty error response without JSON crash', async () => {
  const mockResponse = new Response('', {
    status: 500,
    statusText: 'Internal Server Error',
  })
  await assert.rejects(
    async () => {
      await parseApiResponse(mockResponse, 'Reconciliation failed')
    },
    (err) => {
      assert.match(err.message, /HTTP 500 Internal Server Error/)
      assert.doesNotMatch(err.message, /Unexpected end of JSON input/)
      return true
    }
  )
})

test('parseApiResponse: handles 502 Bad Gateway with JSON detail from Vite proxy', async () => {
  const mockResponse = new Response(
    JSON.stringify({
      detail:
        'Cannot connect to TradeSathi API backend at http://127.0.0.1:8000 (connect ECONNREFUSED 127.0.0.1:8000). Ensure the FastAPI server is running on port 8000 or configure VITE_BACKEND_PORT.',
    }),
    {
      status: 502,
      statusText: 'Bad Gateway',
      headers: { 'Content-Type': 'application/json' },
    }
  )
  await assert.rejects(
    async () => {
      await parseApiResponse(mockResponse, 'Reconciliation analysis failed')
    },
    (err) => {
      assert.equal(err.status, 502)
      assert.match(err.message, /HTTP 502 Bad Gateway/)
      assert.match(err.message, /Cannot connect to TradeSathi API backend at http:\/\/127\.0\.0\.1:8000/)
      assert.match(err.message, /Ensure the FastAPI server is running/)
      return true
    }
  )
})

test('parseApiResponse: handles empty 502 Bad Gateway with actionable diagnostic fallback', async () => {
  const mockResponse = new Response('', {
    status: 502,
    statusText: 'Bad Gateway',
  })
  await assert.rejects(
    async () => {
      await parseApiResponse(mockResponse, 'Reconciliation analysis failed')
    },
    (err) => {
      assert.equal(err.status, 502)
      assert.match(err.message, /HTTP 502 Bad Gateway: TradeSathi API backend is unreachable\./)
      assert.match(err.message, /Verify that the FastAPI server is running/)
      return true
    }
  )
})

