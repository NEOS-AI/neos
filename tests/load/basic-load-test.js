/**
 * NEOS Basic Load Test
 *
 * Tests basic API endpoints under various load scenarios
 *
 * Usage:
 *   k6 run basic-load-test.js
 *   k6 run --vus 50 --duration 5m basic-load-test.js
 *
 * Scenarios:
 *   - Smoke test: 1 VU for 30s
 *   - Load test: Ramp up to 50 VUs over 2 minutes
 *   - Stress test: Ramp up to 200 VUs
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const queryDuration = new Trend('query_duration');
const workflowSuccessRate = new Rate('workflow_success');
const apiCallsCounter = new Counter('api_calls');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:80';
const API_PREFIX = '/api/v1';

// Test configuration
export const options = {
  scenarios: {
    // Smoke test: Minimal load to verify functionality
    smoke: {
      executor: 'constant-vus',
      vus: 1,
      duration: '30s',
      tags: { test_type: 'smoke' },
    },

    // Load test: Gradual ramp-up to target load
    load: {
      executor: 'ramping-vus',
      startTime: '30s',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 10 },  // Ramp up to 10 users
        { duration: '3m', target: 50 },  // Ramp up to 50 users
        { duration: '2m', target: 50 },  // Stay at 50 users
        { duration: '1m', target: 0 },   // Ramp down
      ],
      tags: { test_type: 'load' },
    },

    // Spike test: Sudden traffic spike
    spike: {
      executor: 'ramping-vus',
      startTime: '7m30s',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 100 }, // Spike to 100 users
        { duration: '1m', target: 100 },  // Hold for 1 minute
        { duration: '10s', target: 0 },   // Drop to 0
      ],
      tags: { test_type: 'spike' },
    },
  },

  thresholds: {
    // HTTP request duration should be below 5s for 95% of requests
    'http_req_duration': ['p(95)<5000'],

    // Error rate should be below 5%
    'errors': ['rate<0.05'],

    // 90% of requests should complete successfully
    'http_req_failed': ['rate<0.1'],

    // Workflow success rate should be above 90%
    'workflow_success': ['rate>0.9'],
  },
};

// Test data
const testQueries = [
  'What is machine learning?',
  'Explain quantum computing',
  'How does photosynthesis work?',
  'What are the benefits of renewable energy?',
  'Describe the water cycle',
];

// Helper function to get random query
function getRandomQuery() {
  return testQueries[Math.floor(Math.random() * testQueries.length)];
}

// Helper function to create test user
let userCounter = 0;
function createTestUser() {
  userCounter++;
  const timestamp = Date.now();
  const username = `loadtest_user_${timestamp}_${userCounter}`;
  const email = `${username}@loadtest.com`;
  const password = 'LoadTest123!';

  const payload = JSON.stringify({
    username: username,
    email: email,
    password: password,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
    tags: { name: 'CreateUser' },
  };

  const res = http.post(`${BASE_URL}${API_PREFIX}/register`, payload, params);

  const success = check(res, {
    'user created': (r) => r.status === 200 || r.status === 201,
  });

  if (success && res.json('access_token')) {
    return {
      username: username,
      accessToken: res.json('access_token'),
    };
  }

  return null;
}

// Helper function to login
function loginUser(username, password) {
  const payload = JSON.stringify({
    username: username,
    password: password,
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
    tags: { name: 'Login' },
  };

  const res = http.post(`${BASE_URL}${API_PREFIX}/login`, payload, params);

  check(res, {
    'login successful': (r) => r.status === 200,
    'token received': (r) => r.json('access_token') !== undefined,
  });

  return res.json('access_token');
}

// Main test function
export default function () {
  apiCallsCounter.add(1);

  // Create or use existing test user
  const user = createTestUser();
  if (!user) {
    errorRate.add(1);
    sleep(1);
    return;
  }

  const authHeaders = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${user.accessToken}`,
  };

  // Test 1: Health Check
  const healthRes = http.get(`${BASE_URL}${API_PREFIX}/health`, {
    tags: { name: 'HealthCheck' },
  });

  check(healthRes, {
    'health check status is 200': (r) => r.status === 200,
  });

  // Test 2: Metrics endpoint (unauthenticated)
  const metricsRes = http.get(`${BASE_URL}/metrics`, {
    tags: { name: 'Metrics' },
  });

  check(metricsRes, {
    'metrics available': (r) => r.status === 200,
    'metrics contains prometheus data': (r) => r.body.includes('neos_http_requests_total'),
  });

  // Test 3: Simple Query
  const queryPayload = JSON.stringify({
    query: getRandomQuery(),
    user_id: user.username,
  });

  const queryParams = {
    headers: authHeaders,
    tags: { name: 'Query' },
    timeout: '60s', // Allow up to 60s for AI processing
  };

  const queryStart = Date.now();
  const queryRes = http.post(
    `${BASE_URL}${API_PREFIX}/query`,
    queryPayload,
    queryParams
  );
  const queryEnd = Date.now();

  const querySuccess = check(queryRes, {
    'query status is 200': (r) => r.status === 200,
    'query has response': (r) => r.json('response') !== undefined,
    'query completed in reasonable time': (r) => (queryEnd - queryStart) < 30000,
  });

  // Record metrics
  queryDuration.add(queryEnd - queryStart);
  workflowSuccessRate.add(querySuccess);

  if (!querySuccess) {
    errorRate.add(1);
  }

  // Test 4: Get Query History
  const historyRes = http.get(
    `${BASE_URL}${API_PREFIX}/history?limit=10`,
    {
      headers: authHeaders,
      tags: { name: 'QueryHistory' },
    }
  );

  check(historyRes, {
    'history retrieved': (r) => r.status === 200,
    'history is array': (r) => Array.isArray(r.json()),
  });

  // Simulate user think time
  sleep(Math.random() * 3 + 1); // 1-4 seconds
}

// Setup function (runs once per VU)
export function setup() {
  console.log(`Starting load test against ${BASE_URL}`);

  // Verify API is accessible
  const healthRes = http.get(`${BASE_URL}${API_PREFIX}/health`);

  if (healthRes.status !== 200) {
    throw new Error(`API not accessible. Health check returned ${healthRes.status}`);
  }

  console.log('API is healthy, proceeding with load test');

  return { startTime: Date.now() };
}

// Teardown function (runs once after all iterations)
export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Load test completed in ${duration}s`);
}

// Handle test summary
export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'summary.json': JSON.stringify(data),
    'summary.html': htmlReport(data),
  };
}

// Text summary helper
function textSummary(data, options) {
  const indent = options.indent || '';
  const enableColors = options.enableColors || false;

  let summary = '\n';
  summary += `${indent}Test Summary:\n`;
  summary += `${indent}=============\n\n`;

  // Metrics
  for (const [name, metric] of Object.entries(data.metrics)) {
    if (metric.values) {
      summary += `${indent}${name}:\n`;
      summary += `${indent}  min: ${metric.values.min}\n`;
      summary += `${indent}  max: ${metric.values.max}\n`;
      summary += `${indent}  avg: ${metric.values.avg}\n`;
      summary += `${indent}  p95: ${metric.values['p(95)']}\n\n`;
    }
  }

  return summary;
}

// HTML report helper
function htmlReport(data) {
  return `
<!DOCTYPE html>
<html>
<head>
  <title>NEOS Load Test Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    h1 { color: #333; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    th { background-color: #4CAF50; color: white; }
    tr:nth-child(even) { background-color: #f2f2f2; }
    .pass { color: green; }
    .fail { color: red; }
  </style>
</head>
<body>
  <h1>NEOS Load Test Report</h1>
  <p>Generated: ${new Date().toISOString()}</p>

  <h2>Test Configuration</h2>
  <ul>
    <li>Target: ${BASE_URL}</li>
    <li>Duration: ${JSON.stringify(options.scenarios)}</li>
  </ul>

  <h2>Results</h2>
  <pre>${JSON.stringify(data, null, 2)}</pre>
</body>
</html>
`;
}
