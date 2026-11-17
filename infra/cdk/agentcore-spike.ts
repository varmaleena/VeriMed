import {
  CfnOutput,
  Stack,
  StackProps,
  Names,
  Duration,
  RemovalPolicy,
  Validations,
} from "aws-cdk-lib";
import {
  CfnGateway,
  CfnGatewayTarget,
  CfnRuntime,
} from "aws-cdk-lib/aws-bedrockagentcore";
import {
  OAuthScope,
  ResourceServerScope,
  UserPool,
  UserPoolClient,
} from "aws-cdk-lib/aws-cognito";
import {
  Role,
  ServicePrincipal,
  Policy,
  PolicyStatement,
} from "aws-cdk-lib/aws-iam";
import { Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { Asset } from "aws-cdk-lib/aws-s3-assets";
import { Construct } from "constructs";

interface AgentCoreSpikeProps extends StackProps {
  bundle: string;
  profileId: string;
  modelArns: string[];
}

export class AgentCoreSpike extends Stack {
  constructor(scope: Construct, id: string, props: AgentCoreSpikeProps) {
    super(scope, id, props);
    const pool = new UserPool(this, "Pool", {
      selfSignUpEnabled: false,
      removalPolicy: RemovalPolicy.DESTROY,
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
    });
    for (const rule of ["COG2", "COG8"]) {
      Validations.of(pool).acknowledge({
        id: `AwsSolutions::AwsSolutions-${rule}`,
        reason:
          "The disposable spike pool has no users or interactive authentication. Its sole client uses OAuth client credentials.",
      });
    }
    const invoke = new ResourceServerScope({
      scopeName: "invoke",
      scopeDescription: "Invoke the synthetic spike",
    });
    const server = pool.addResourceServer("Api", {
      identifier: "verimed-spike",
      scopes: [invoke],
    });
    const client = new UserPoolClient(this, "Client", {
      userPool: pool,
      generateSecret: true,
      accessTokenValidity: Duration.minutes(10),
      oAuth: {
        flows: { clientCredentials: true },
        scopes: [OAuthScope.resourceServer(server, invoke)],
      },
    });
    const domain = pool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: `verimed-spike-${Names.uniqueId(this).toLowerCase().slice(-8)}-${this.account}`,
      },
    });
    const jwt = {
      customJwtAuthorizer: {
        discoveryUrl: `https://cognito-idp.${this.region}.${this.urlSuffix}/${pool.userPoolId}/.well-known/openid-configuration`,
        allowedClients: [client.userPoolClientId],
      },
    };
    const execution = new Role(this, "HelloRole", {
      assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    });
    const logs = new LogGroup(this, "HelloLogs", {
      retention: RetentionDays.ONE_DAY,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    logs.grantWrite(execution);
    const hello = new Function(this, "Hello", {
      runtime: Runtime.PYTHON_3_14,
      handler: "index.handler",
      code: Code.fromInline(
        "def handler(event, context):\n    return {'greeting': 'hello-from-verimed-gateway'}\n",
      ),
      role: execution,
      logGroup: logs,
      timeout: Duration.seconds(5),
    });
    const service = new ServicePrincipal("bedrock-agentcore.amazonaws.com", {
      conditions: { StringEquals: { "aws:SourceAccount": this.account } },
    });
    const gatewayRole = new Role(this, "GatewayRole", { assumedBy: service });
    const gatewayPolicy = new Policy(this, "GatewayInvoke", {
      roles: [gatewayRole],
      statements: [
        new PolicyStatement({
          actions: ["lambda:InvokeFunction"],
          resources: [hello.functionArn],
        }),
      ],
    });
    const gateway = new CfnGateway(this, "Gateway", {
      name: "verimed-phase0-spike",
      authorizerType: "CUSTOM_JWT",
      authorizerConfiguration: jwt,
      protocolType: "MCP",
      roleArn: gatewayRole.roleArn,
    });
    gateway.node.addDependency(gatewayPolicy);
    const target = new CfnGatewayTarget(this, "Target", {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: "spike",
      credentialProviderConfigurations: [
        { credentialProviderType: "GATEWAY_IAM_ROLE" },
      ],
      targetConfiguration: {
        mcp: {
          lambda: {
            lambdaArn: hello.functionArn,
            toolSchema: {
              inlinePayload: [
                {
                  name: "hello",
                  description: "Return the VeriMed greeting",
                  inputSchema: { type: "object", properties: {} },
                },
              ],
            },
          },
        },
      },
    });
    const bundle = new Asset(this, "RuntimeBundle", { path: props.bundle });
    const runtimeRole = new Role(this, "RuntimeRole", { assumedBy: service });
    const runtimePolicy = new Policy(this, "RuntimeInvoke", {
      roles: [runtimeRole],
      statements: [
        new PolicyStatement({
          actions: ["s3:GetObject"],
          resources: [bundle.bucket.arnForObjects(bundle.s3ObjectKey)],
        }),
        new PolicyStatement({
          actions: [
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
          ],
          resources: props.modelArns,
        }),
      ],
    });
    const runtime = new CfnRuntime(this, "Runtime", {
      agentRuntimeName: "verimed_phase0_spike",
      agentRuntimeArtifact: {
        codeConfiguration: {
          code: {
            s3: { bucket: bundle.s3BucketName, prefix: bundle.s3ObjectKey },
          },
          entryPoint: ["main.py"],
          runtime: "PYTHON_3_12",
        },
      },
      networkConfiguration: { networkMode: "PUBLIC" },
      protocolConfiguration: "HTTP",
      authorizerConfiguration: jwt,
      requestHeaderConfiguration: { requestHeaderAllowlist: ["Authorization"] },
      roleArn: runtimeRole.roleArn,
      environmentVariables: {
        MODEL_CHALLENGER_ID: props.profileId,
        AGENTCORE_GATEWAY_URL: gateway.attrGatewayUrl,
        VERIMED_SPIKE_TOOL_NAME: "spike___hello",
      },
    });
    runtime.node.addDependency(target, runtimePolicy);
    Validations.of(hello).acknowledge({
      id: "AwsSolutions::AwsSolutions-L1",
      reason: "Python 3.14 is used for the temporary native Lambda handler.",
    });
    new CfnOutput(this, "RuntimeArn", { value: runtime.attrAgentRuntimeArn });
    new CfnOutput(this, "PoolId", { value: pool.userPoolId });
    new CfnOutput(this, "ClientId", { value: client.userPoolClientId });
    new CfnOutput(this, "TokenUrl", {
      value: `${domain.baseUrl()}/oauth2/token`,
    });
  }
}
