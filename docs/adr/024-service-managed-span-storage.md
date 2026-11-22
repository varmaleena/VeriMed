# ADR 024: Service-managed encrypted span storage

Date: 2026-11-22
Status: Accepted; deployed and verified in the dev cell.

CloudWatch reserves the aws/ log-group prefix; direct CreateLogGroup for aws/spans fails.
Let X-Ray create aws/spans through TransactionSearchConfig.CloudWatchLogsConfiguration.
Supply the cell trace CMK there instead of declaring a reserved-name LogGroup.
The live regional CloudFormation schema supports this property; CDK's bundled validator lagged.
A resource-scoped F3002 acknowledgement records that schema discrepancy.
A least-privilege custom resource sets thirty-day retention after service creation.
Its handler never logs CloudFormation events, including their signed callback URLs.
The helper used Node.js 24, verified as GA at the deployment checkpoint on November 20.
An initial failed deployment's empty data group was removed and unused CMK scheduled for deletion.
The replacement stack and API update completed; actual spans have CMK encryption and 30-day retention.
Real Cognito SRP and negative authorization checks passed; the temporary user was deleted.
Evidence: ../tracing-verification.json. Web-to-API correlation remains a separate acceptance gate.
Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-xray-transactionsearchconfig.html
Source: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_CreateLogGroup.html
