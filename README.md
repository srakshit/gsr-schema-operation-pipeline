# gsr-schema-operation-pipeline
Pipeline to register new schema and notify dependents of the schema.

Clone git repo `https://github.com/srakshit/gsr-schema-operation-pipeline`

Create a S3 bucket named - `gsr-schema-pipeline-<<Account-ID>` to upload the lambda packages and the avro schema code.

Copy and execute the following set of commands to upload customer avro schema code to S3

    cd schema_customer
    zip -r --exclude="target/*" --exclude="*.DS_Store*" ../schema_customer.zip .
    cd ..
    aws s3 cp schema_customer.zip s3://gsr-schema-pipeline-<<Account-ID>>/customer_schema/
    rm schema_customer.zip

Copy and execute the following set of commands to package codecommit lambda function and upload it to S3. Replace <<Account ID>> with your AWS AcountID<br>

This lambda function is triggered by CodeCommit repo commits.

    cd codecommit_trigger_build
    pip install -r requirements.txt --target ./package
    cd package
    zip -r ../../codecommit_lambda.zip .
    cd ..
    zip -g ../codecommit_lambda.zip lambda_function.py
    cd ..
    aws s3 cp codecommit_lambda.zip s3://gsr-schema-pipeline-<<Account-ID>>/codecommit-trigger/
    rm codecommit_lambda.zip

Copy and execute the following set of commands to package event rule lambda function and upload it to S3. Replace <<Account ID>> with your AWS AcountID<br>

This lambda function is triggered by EventBridge when codebuild notification status is received.

    cd codebuild_notification
    pip install -r requirements.txt --target ./package
    cd package
    zip -r ../../eventrule_lambda.zip .
    cd ..
    zip -g ../eventrule_lambda.zip lambda_function.py
    cd ..
    aws s3 cp eventrule_lambda.zip s3://gsr-schema-pipeline-<<Account-ID>>/codebuild-notification/
    rm eventrule_lambda.zip

Deploy the CFN stack.

Provide the following input parameters:

- Stack Name
- CodeS3Bucket (Provide the S3 bucket name created as per instructions above)
- TeamEmail (Provide your email address to receive email notification when schema is created in AWS Glue Schema Registry)

Keep other CloudFormation parameters to default value.

Once the stack is deployed, you would see a CodeBuild project is triggered. Wait for this project to fail before moving on to the next step.

You would have receive an email to confirm subscription to SNS topic. Confirm the subscription to receive notification.

Get the `CodeCommitRepositoryCloneUrl` from Cloudformation output.
Open the AWS Cloud9. You can get the Cloud9IDE url from CloudFormation output.

Git clone the repo in Cloud9.

Execute the below set of commands to replace certain values in `buildspec.yml`, `manifest.yml`, `pom.xml`, `settings.xml`

    cd schema-customer
    export region=<<Region>>
    export account_id=<<Account-ID>>
    export codeartifact_domain_name=gsr-schema-domain
    export codeartifact_repo_name=gsr-schema-mvn-repo
    export codecommit_repo=schema-customer
    export user_email=<<Your Email>>
    export user_name=<<Your Name>>

    sed -i "s/<<region>>/$region/g" manifest.yml pom.xml settings.xml buildspec.yml
    sed -i "s/<<codeartifact-domain-name>>/$codeartifact_domain_name/g" pom.xml settings.xml buildspec.yml
    sed -i "s/<<codeartifact-repo-name>>/$codeartifact_repo_name/g" pom.xml settings.xml
    sed -i "s/<<account-id>>/$account_id/g" pom.xml settings.xml buildspec.yml
    sed -i "s/<<codecommit-repo>>/$codecommit_repo/g" pom.xml
    sed -i "s/<<user-email>>/$user_email/g" buildspec.yml manifest.yml
    sed -i "s/<<user-name>>/$user_name/g" buildspec.yml manifest.yml

    git add manifest.yml pom.xml settings.xml buildspec.yml
    git commit -am "Integrated with CodeArtifact"
    git push

This would trigger a build. Check AWS Glue Schema Registry, CodeBuild, CodeArtifact. Also you should receive an email confirming a new customer schema is created.

Update the `Customer.avsc` file and git push to the CodeCommit repo.

This should trigger another build and a new version of schema would be registered in AWS Glue Schema Registry and the generated POJO JAR can be found in the CodeArtifact.