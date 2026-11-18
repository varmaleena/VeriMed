import {
  CfnOutput,
  Duration,
  Names,
  Stack,
  StackProps,
  Validations,
} from "aws-cdk-lib";
import {
  CfnUserPoolGroup,
  Mfa,
  OAuthScope,
  UserPool,
  UserPoolClient,
  AccountRecovery,
} from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";

export class CellIdentity extends Stack {
  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    const pool = new UserPool(this, "Users", {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      accountRecovery: AccountRecovery.EMAIL_ONLY,
      mfa: Mfa.REQUIRED,
      mfaSecondFactor: { sms: false, otp: true },
      passwordPolicy: {
        minLength: 14,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
    });
    Validations.of(pool).acknowledge({
      id: "AwsSolutions::AwsSolutions-COG8",
      reason:
        "The first dev slice uses mandatory TOTP on the default feature plan. Plus-tier threat protection remains a production rollout decision.",
    });
    const client = new UserPoolClient(this, "WebClient", {
      userPool: pool,
      generateSecret: true,
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
      accessTokenValidity: Duration.minutes(15),
      idTokenValidity: Duration.minutes(15),
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [OAuthScope.OPENID, OAuthScope.PROFILE],
        callbackUrls: ["http://localhost:3000/api/auth/callback/cognito"],
        logoutUrls: ["http://localhost:3000/login"],
      },
    });
    const domain = pool.addDomain("LoginDomain", {
      cognitoDomain: {
        domainPrefix: `verimed-dev-${this.account}-${Names.uniqueId(this).toLowerCase().slice(-8)}`,
      },
    });
    for (const role of [
      "PHYSICIAN",
      "PHARMACIST",
      "CODER",
      "AUDITOR",
      "TENANT_ADMIN",
    ]) {
      new CfnUserPoolGroup(this, role, {
        userPoolId: pool.userPoolId,
        groupName: role,
      });
    }
    new CfnOutput(this, "UserPoolId", { value: pool.userPoolId });
    new CfnOutput(this, "ClientId", { value: client.userPoolClientId });
    new CfnOutput(this, "Issuer", {
      value: `https://cognito-idp.${this.region}.${this.urlSuffix}/${pool.userPoolId}`,
    });
    new CfnOutput(this, "LoginDomainUrl", { value: domain.baseUrl() });
  }
}
