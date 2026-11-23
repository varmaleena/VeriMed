import {
  ArnFormat,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import { Construct } from "constructs";
import { Key } from "aws-cdk-lib/aws-kms";
import {
  Bucket,
  BlockPublicAccess,
  BucketEncryption,
} from "aws-cdk-lib/aws-s3";
import { Secret } from "aws-cdk-lib/aws-secretsmanager";
import { PolicyStatement, Role, ServicePrincipal } from "aws-cdk-lib/aws-iam";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import {
  CfnWebFunction,
  CfnWebFunctionRevision,
  CfnWebFunctionEndpoint,
  CfnResourcePolicy,
} from "aws-cdk-lib/aws-lambda";
import {
  AllowedMethods,
  CachePolicy,
  CfnOriginAccessControl,
  Distribution,
  HeadersFrameOption,
  OriginProtocolPolicy,
  OriginRequestPolicy,
  OriginSslPolicy,
  ResponseHeadersPolicy,
  ViewerProtocolPolicy,
} from "aws-cdk-lib/aws-cloudfront";
import { HttpOrigin } from "aws-cdk-lib/aws-cloudfront-origins";
import { CfnWebACL } from "aws-cdk-lib/aws-wafv2";

interface WebProps extends StackProps {
  stage: string;
  tenant: string;
}

export class CellWebAssets extends Stack {
  constructor(scope: Construct, id: string, props: WebProps) {
    super(scope, id, props);
    for (const [name, value] of Object.entries({
      Project: "verimed",
      Env: props.stage,
      Tenant: props.tenant,
    }))
      Tags.of(this).add(name, value);
    const key = new Key(this, "Key", {
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const bucketName = `chartvigil-${this.account}-${this.region}-${props.stage}-${props.tenant}-web-code`;
    const bucket = new Bucket(this, "Code", {
      bucketName,
      encryption: BucketEncryption.KMS,
      encryptionKey: key,
      enforceSSL: true,
      versioned: true,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    bucket.addToResourcePolicy(
      new PolicyStatement({
        principals: [new ServicePrincipal("lambda.amazonaws.com")],
        actions: ["s3:GetObject", "s3:GetObjectVersion"],
        resources: [bucket.arnForObjects("revisions/*")],
        conditions: { StringEquals: { "aws:SourceAccount": this.account } },
      }),
    );
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [new ServicePrincipal("lambda.amazonaws.com")],
        actions: ["kms:Decrypt"],
        resources: ["*"],
        conditions: {
          StringLike: {
            "aws:SourceArn": `arn:${this.partition}:lambda:${this.region}:${this.account}:web-function/chartvigil-${props.stage}-${props.tenant}-web/revision/*`,
            "kms:EncryptionContext:aws:lambda:WebFunctionRevisionArn": `arn:${this.partition}:lambda:${this.region}:${this.account}:web-function/chartvigil-${props.stage}-${props.tenant}-web/revision/*`,
          },
        },
      }),
    );
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [new ServicePrincipal("lambda.amazonaws.com")],
        actions: ["kms:Decrypt"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `s3.${this.region}.${this.urlSuffix}`,
          },
          StringLike: {
            "kms:EncryptionContext:aws:s3:arn": `arn:${this.partition}:s3:::${bucketName}/revisions/*`,
          },
        },
      }),
    );
    key.addToResourcePolicy(
      new PolicyStatement({
        principals: [
          new ServicePrincipal(`logs.${this.region}.${this.urlSuffix}`),
        ],
        actions: [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ],
        resources: ["*"],
        conditions: {
          ArnEquals: {
            "kms:EncryptionContext:aws:logs:arn": ["", ".local"].map(
              (suffix) =>
                `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:/verimed/${props.stage}/${props.tenant}/web${suffix}`,
            ),
          },
        },
      }),
    );
    const secret = new Secret(this, "AuthSecret", {
      encryptionKey: key,
      generateSecretString: { passwordLength: 64, excludePunctuation: true },
    });
    Validations.of(bucket).acknowledge({
      id: "AwsSolutions::AwsSolutions-S1",
      reason:
        "Private deployment artifacts only; no clinical content or public access. CloudTrail data-event coverage is a production operations gate.",
    });
    Validations.of(secret).acknowledge({
      id: "AwsSolutions::AwsSolutions-SMG4",
      reason:
        "Auth.js signing material rotates through explicit staged deployment to avoid invalidating active sessions unexpectedly; automatic rotation needs an application-aware rollout.",
    });
    new CfnOutput(this, "CodeBucket", { value: bucket.bucketName });
    new CfnOutput(this, "KeyArn", { value: key.keyArn });
    new CfnOutput(this, "AuthSecretArn", { value: secret.secretArn });
  }
}

interface CellWebProps extends WebProps {
  bucket: string;
  objectKey: string;
  objectVersion: string;
  keyArn: string;
  authSecretArn: string;
  userPoolId: string;
  clientId: string;
  issuer: string;
  apiUrl: string;
  publicOrigin: string;
}

export class CellWeb extends Stack {
  constructor(scope: Construct, id: string, props: CellWebProps) {
    super(scope, id, props);
    if (props.stage !== "dev" || this.region !== "us-east-1")
      throw new Error(
        "Managed web deployment is restricted to the reviewed us-east-1 dev cell",
      );
    if (!props.objectKey.startsWith("revisions/") || !props.objectVersion)
      throw new Error("An immutable versioned web artifact is required");
    const origin = new URL(props.publicOrigin);
    if (
      origin.protocol !== "https:" ||
      origin.origin !== props.publicOrigin ||
      origin.username ||
      origin.password
    )
      throw new Error("A fixed HTTPS public origin is required");
    for (const [name, value] of Object.entries({
      Project: "verimed",
      Env: props.stage,
      Tenant: props.tenant,
    }))
      Tags.of(this).add(name, value);
    const key = Key.fromKeyArn(this, "Key", props.keyArn);
    const logName = `/verimed/${props.stage}/${props.tenant}/web`;
    const logs = [logName, logName + ".local"].map(
      (name, index) =>
        new LogGroup(this, `Logs${index}`, {
          logGroupName: name,
          encryptionKey: key,
          retention: RetentionDays.ONE_MONTH,
          removalPolicy: RemovalPolicy.RETAIN,
        }),
    );
    const role = new Role(this, "RuntimeRole", {
      assumedBy: new ServicePrincipal("lambda.amazonaws.com"),
    });
    role.addToPolicy(
      new PolicyStatement({
        actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [logName, logName + ".local"].map(
          (name) =>
            `arn:${this.partition}:logs:${this.region}:${this.account}:log-group:${name}:log-stream:*`,
        ),
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [props.authSecretArn],
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["cognito-idp:DescribeUserPoolClient"],
        resources: [
          this.formatArn({
            service: "cognito-idp",
            resource: "userpool",
            resourceName: props.userPoolId,
            arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
          }),
        ],
      }),
    );
    key.grantDecrypt(role);
    const fn = new CfnWebFunction(this, "Function", {
      functionName: `chartvigil-${props.stage}-${props.tenant}-web`,
    });
    const revision = new CfnWebFunctionRevision(this, "Revision", {
      functionName: fn.ref,
      kmsKeyArn: props.keyArn,
      buildConfig: {
        codeConfig: {
          s3Object: {
            bucket: props.bucket,
            key: props.objectKey,
            versionId: props.objectVersion,
          },
        },
        runtimeConfig: { runtime: "nodejs24.x" },
      },
      serviceConfig: {
        executionRoleArn: role.roleArn,
        timeoutSeconds: 40,
        maxConcurrencyPerEnvironment: 8,
        environmentVariables: {
          AWS_LAMBDA_NODEJS_ENTRYPOINT: "index.cjs",
          VERIMED_HOSTED_WEB: "true",
          VERIMED_TENANT_NAME: `Tenant ${props.tenant}`,
          VERIMED_ENV: props.stage,
          WEB_AUTH_SECRET_ARN: props.authSecretArn,
          COGNITO_USER_POOL_ID: props.userPoolId,
          AUTH_COGNITO_ID: props.clientId,
          AUTH_COGNITO_ISSUER: props.issuer,
          AUTH_URL: props.publicOrigin,
          CELL_API_URL: props.apiUrl,
        },
        telemetryConfig: {
          loggingConfig: {
            logGroup: logName,
            applicationLogLevel: "INFO",
            systemLogLevel: "WARN",
          },
        },
      },
    });
    revision.node.addDependency(role);
    revision.node.addDependency(...logs);
    const endpoint = new CfnWebFunctionEndpoint(this, "Endpoint", {
      functionName: fn.ref,
      endpointName: "dev",
      endpointType: "HomeRegion",
      authType: "IamAuth",
      revisionWeights: [{ revisionId: revision.attrRevisionId, weight: 100 }],
      scalingConfig: { maxEnvironments: 2 },
      throttleConfig: { rateLimit: 100 },
    });
    const oac = new CfnOriginAccessControl(this, "Oac", {
      originAccessControlConfig: {
        name: `${this.stackName}-web`,
        originAccessControlOriginType: "lambda",
        signingBehavior: "always-amz-auth",
        signingProtocol: "sigv4",
      },
    });
    const acl = new CfnWebACL(this, "Waf", {
      scope: "CLOUDFRONT",
      defaultAction: { allow: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: `${this.stackName}-web`,
        sampledRequestsEnabled: false,
      },
      rules: ["AWSManagedRulesCommonRuleSet", "AWSManagedRulesSQLiRuleSet"].map(
        (name, priority) => ({
          name,
          priority,
          overrideAction: { none: {} },
          statement: { managedRuleGroupStatement: { vendorName: "AWS", name } },
          visibilityConfig: {
            cloudWatchMetricsEnabled: true,
            metricName: name,
            sampledRequestsEnabled: false,
          },
        }),
      ),
    });
    const headers = new ResponseHeadersPolicy(this, "Headers", {
      securityHeadersBehavior: {
        strictTransportSecurity: {
          accessControlMaxAge: Duration.days(365),
          includeSubdomains: true,
          override: true,
        },
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: HeadersFrameOption.DENY, override: true },
      },
    });
    const distribution = new Distribution(this, "Distribution", {
      webAclId: acl.attrArn,
      defaultBehavior: {
        origin: new HttpOrigin(endpoint.attrDomainName, {
          protocolPolicy: OriginProtocolPolicy.HTTPS_ONLY,
          originSslProtocols: [OriginSslPolicy.TLS_V1_2],
          originAccessControlId: oac.attrId,
          readTimeout: Duration.seconds(60),
        }),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_ALL,
        cachePolicy: CachePolicy.CACHING_DISABLED,
        originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        responseHeadersPolicy: headers,
      },
    });
    new CfnResourcePolicy(this, "OriginPolicy", {
      resourceArn: fn.attrFunctionArn,
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "cloudfront.amazonaws.com" },
            Action: "lambda:InvokeWebFunctionEndpoint",
            Resource: endpoint.attrEndpointArn,
            Condition: {
              StringEquals: { "aws:SourceArn": distribution.distributionArn },
            },
          },
        ],
      },
    });
    for (const name of [logName, logName + ".local"])
      Validations.of(role).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:logs:${this.region}:${this.account}:log-group:${name}:log-stream:*]`,
        reason:
          "Only streams in this web runtime's two encrypted log groups may be written.",
      });
    Validations.of(distribution).acknowledge({
      id: "AwsSolutions::AwsSolutions-CFR1",
      reason:
        "The synthetic-data dev URL supports distributed testing. Production geography restrictions require tenant-specific permitted countries.",
    });
    Validations.of(distribution).acknowledge({
      id: "AwsSolutions::AwsSolutions-CFR4",
      reason:
        "The owner selected the AWS-managed CloudFront hostname. Its default certificate uses CloudFront's managed TLS policy; a custom-domain certificate is not available.",
    });
    Validations.of(distribution).acknowledge({
      id: "AwsSolutions::AwsSolutions-CFR3",
      reason:
        "Raw access logs expose clinical URLs and cookies; retain only categorical application logs and WAF metrics, with request sampling disabled.",
    });
    new CfnOutput(this, "WebUrl", {
      value: `https://${distribution.distributionDomainName}`,
    });
    new CfnOutput(this, "OriginDomain", { value: endpoint.attrDomainName });
  }
}
