# 007 — Password-only demo sign-in

The owner requested removing MFA from the synthetic-data demo on November 18, 2026.
Deploy CellIdentity with both cellIdentity=true and demoWithoutMfa=true.
This sets the Cognito user pool MFA configuration to OFF through CDK.
An explicit demo property controls the exception.
The default identity configuration requires TOTP.
Password authentication and the authorization-code flow continue to protect demo access.
The cdk-nag MFA finding is acknowledged with this documented owner decision.
The demo test expects password-only sign-in after signing out.
Re-enable TOTP by deploying demoWithoutMfa=false before testing the standard authentication flow.
