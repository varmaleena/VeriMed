// Infrastructure-only handler. Never log CFN events: ResponseURL is a signed credential.
export const SPAN_RETENTION_HANDLER = `
const { CloudWatchLogsClient, PutRetentionPolicyCommand } = require('@aws-sdk/client-cloudwatch-logs');
exports.handler = async (event) => {
  let target;
  try {
    target = new URL(event.ResponseURL);
    if (target.protocol !== 'https:' || !target.hostname.startsWith('cloudformation-custom-resource-response-') ||
        !target.hostname.endsWith('.amazonaws.com')) throw new Error();
  } catch { throw new Error('Invalid CFN callback'); }
  let status = 'SUCCESS';
  try {
    if (!['Create', 'Update', 'Delete'].includes(event.RequestType) ||
        event.ResourceProperties.LogGroupName !== 'aws/spans' ||
        ![30, '30'].includes(event.ResourceProperties.RetentionInDays)) throw new Error('Invalid retention configuration');
    if (event.RequestType !== 'Delete') {
      await new CloudWatchLogsClient({}).send(new PutRetentionPolicyCommand({ logGroupName: 'aws/spans', retentionInDays: 30 }), { abortSignal: AbortSignal.timeout(10000) });
    }
  } catch {
    status = 'FAILED';
    console.error(JSON.stringify({ event: 'trace_retention_failed', error_code: 'TRACE_RETENTION_FAILED' }));
  }
  const body = JSON.stringify({ Status: status, Reason: status === 'SUCCESS' ? 'Retention configured' : 'Retention configuration failed',
    PhysicalResourceId: 'verimed-spans-retention', StackId: event.StackId, RequestId: event.RequestId,
    LogicalResourceId: event.LogicalResourceId, NoEcho: true, Data: {} });
  try {
    const response = await fetch(target, { method: 'PUT', body, headers: { 'content-type': '', 'content-length': String(Buffer.byteLength(body)) },
      redirect: 'error', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error();
  } catch { throw new Error('CFN callback delivery failed'); }
};
`;
