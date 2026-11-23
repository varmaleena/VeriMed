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

interface CellIdentityProps extends StackProps {
  demoWithoutMfa?: boolean;
  hostedOrigin?: string;
}

export class CellIdentity extends Stack {
  constructor(scope: Construct, id: string, props: CellIdentityProps) {
    super(scope, id, props);
    if (props.hostedOrigin) {
      const origin = new URL(props.hostedOrigin);
      if (
        origin.protocol !== "https:" ||
        origin.origin !== props.hostedOrigin ||
        !origin.hostname.endsWith(".cloudfront.net")
      )
        throw new Error(
          "The hosted callback must be a fixed AWS-managed CloudFront HTTPS origin",
        );
    }
    const pool = new UserPool(this, "Users", {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      accountRecovery: AccountRecovery.EMAIL_ONLY,
      mfa: props.demoWithoutMfa ? Mfa.OFF : Mfa.REQUIRED,
      mfaSecondFactor: props.demoWithoutMfa
        ? undefined
        : { sms: false, otp: true },
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
        "The dev slice uses the default feature plan. Plus-tier threat protection remains a production rollout decision.",
    });
    if (props.demoWithoutMfa) {
      Validations.of(pool).acknowledge({
        id: "AwsSolutions::AwsSolutions-COG2",
        reason:
          "The owner explicitly requested password-only sign-in for the synthetic-data demo. See ADR 007.",
      });
    }
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
        callbackUrls: [
          "http://localhost:3000/api/auth/callback/cognito",
          ...(props.hostedOrigin
            ? [`${props.hostedOrigin}/api/auth/callback/cognito`]
            : []),
        ],
        logoutUrls: [
          "http://localhost:3000/login",
          ...(props.hostedOrigin ? [`${props.hostedOrigin}/login`] : []),
        ],
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
