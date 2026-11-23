import "server-only";
import {
  SecretsManagerClient,
  GetSecretValueCommand,
} from "@aws-sdk/client-secrets-manager";
import {
  CognitoIdentityProviderClient,
  DescribeUserPoolClientCommand,
} from "@aws-sdk/client-cognito-identity-provider";

/** Load secrets with the execution role, before Auth.js handles any requests. */
export async function loadHostedIdentity(): Promise<void> {
  try {
    const region = process.env.AWS_REGION;
    const secretId = process.env.WEB_AUTH_SECRET_ARN;
    const userPoolId = process.env.COGNITO_USER_POOL_ID;
    const clientId = process.env.AUTH_COGNITO_ID;
    const origin = new URL(process.env.AUTH_URL ?? "");
    if (
      !region ||
      !secretId ||
      !userPoolId ||
      !clientId ||
      origin.protocol !== "https:" ||
      origin.pathname !== "/" ||
      origin.username ||
      origin.password ||
      origin.search ||
      origin.hash
    )
      throw new Error("Invalid hosted configuration");
    const options = { abortSignal: AbortSignal.timeout(6000) };
    const [secret, identity] = await Promise.all([
      new SecretsManagerClient({ region, maxAttempts: 2 }).send(
        new GetSecretValueCommand({ SecretId: secretId }),
        options,
      ),
      new CognitoIdentityProviderClient({ region, maxAttempts: 2 }).send(
        new DescribeUserPoolClientCommand({
          UserPoolId: userPoolId,
          ClientId: clientId,
        }),
        options,
      ),
    ]);
    if (
      !secret.SecretString ||
      secret.SecretString.length < 32 ||
      !identity.UserPoolClient?.ClientSecret
    )
      throw new Error("Identity material unavailable");
    process.env.AUTH_SECRET = secret.SecretString;
    process.env.AUTH_COGNITO_SECRET = identity.UserPoolClient.ClientSecret;
    process.env.AUTH_TRUST_HOST = "true";
  } catch {
    // Never include SDK responses, OAuth material or error metadata in logs.
    throw new Error("HOSTED_IDENTITY_INITIALIZATION_FAILED");
  }
}
