/**
 * Base URL for every backend call. This one line is the entire environment
 * story: locally it resolves through the CORS proxy (bin/proxy-server.js,
 * port 3001), which strips the "/api/employee-directory" prefix before
 * forwarding to the LocalStack Lambda Function URL. On AWS it resolves
 * through CloudFront, whose "/api/employee-directory*" cache behavior
 * forwards the full, unstripped path to the same Lambda, which strips the
 * prefix itself (see backend/employee-directory/function.py). No branching
 * needed here.
 */
const BASE_URL = `${import.meta.env.VITE_API_URL}/api/employee-directory`;

/**
 * Calls the service's liveness endpoint.
 *
 * @returns {Promise<{status: string}>} The parsed JSON response body.
 */
export async function getHealth() {
  const response = await fetch(`${BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json();
}
