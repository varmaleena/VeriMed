import {
  CfnOutput,
  Duration,
  Stack,
  StackProps,
  Tags,
  Validations,
} from "aws-cdk-lib";
import {
  CfnOIDCProvider,
  FederatedPrincipal,
  PolicyStatement,
  Role,
} from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

interface GitHubDeployProps extends StackProps {
  repository: string;
  ownerId: string;
  repositoryId: string;
  qualifier: string;
}

/** Dev deployment federation only; account creation and runtime data access are not granted. */
export class GitHubDeploy extends Stack {
  constructor(scope: Construct, id: string, props: GitHubDeployProps) {
    super(scope, id, props);
    if (
      !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(props.repository) ||
      !/^[a-z0-9]+$/.test(props.qualifier) ||
      !/^\d+$/.test(props.ownerId) ||
      !/^\d+$/.test(props.repositoryId)
    )
      throw new Error(
        "Explicit GitHub repository and bootstrap qualifier are required",
      );
    for (const [key, value] of Object.entries({
      Project: "verimed",
      Env: "dev",
      Tenant: "a",
    }))
      Tags.of(this).add(key, value);
    const provider = new CfnOIDCProvider(this, "GitHub", {
      url: "https://token.actions.githubusercontent.com",
      clientIdList: ["sts.amazonaws.com"],
    });
    const role = new Role(this, "DeployRole", {
      maxSessionDuration: Duration.hours(1),
      assumedBy: new FederatedPrincipal(
        provider.attrArn,
        {
          StringEquals: {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": `repo:${props.repository.split("/")[0]}@${props.ownerId}/${props.repository.split("/")[1]}@${props.repositoryId}:environment:dev`,
          },
        },
        "sts:AssumeRoleWithWebIdentity",
      ),
    });
    role.addToPolicy(
      new PolicyStatement({
        actions: ["sts:AssumeRole"],
        resources: [
          "deploy",
          "file-publishing",
          "image-publishing",
          "lookup",
        ].map(
          (kind) =>
            `arn:${this.partition}:iam::${this.account}:role/cdk-${props.qualifier}-${kind}-role-${this.account}-${this.region}`,
        ),
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["ssm:GetParameter"],
        resources: [
          `arn:${this.partition}:ssm:${this.region}:${this.account}:parameter/cdk-bootstrap/${props.qualifier}/version`,
        ],
      }),
    );
    role.addToPolicy(
      new PolicyStatement({
        actions: ["cloudformation:DescribeStacks"],
        resources: [
          `arn:${this.partition}:cloudformation:${this.region}:${this.account}:stack/CDKToolkit/*`,
          `arn:${this.partition}:cloudformation:${this.region}:${this.account}:stack/CellFoundation/*`,
        ],
      }),
    );
    for (const name of ["CDKToolkit", "CellFoundation"])
      Validations.of(role).acknowledge({
        id: `AwsSolutions::AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:cloudformation:${this.region}:${this.account}:stack/${name}/*]`,
        reason:
          "Read-only DescribeStacks is scoped to the bootstrap and dev foundation stack; the suffix is CloudFormation's generated stack ID.",
      });
    new CfnOutput(this, "RoleArn", { value: role.roleArn });
  }
}
