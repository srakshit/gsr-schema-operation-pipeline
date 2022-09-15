# schema_customer repository
Repository to store customer schema.

<br>

## Schema Repository Structure

To register schemas through pipeline, each schema needs its own repository. Here is the structure of the repo which contains the required files, including the Avro schema. 

```console
- schema_customer
 -- src/main/resources/avro
    --- customer.avsc
 -- buildspec.yaml
 -- manifest.yaml
 -- pom.xml
 -- settings.xml
```
1. customer.avsc - Avro schema file that needs to be registered with AWS Glue Schema Registry.
2. buildspec.yml - AWS CodeBuild spec file, containing build details.
3. manifest.yml – Manifest file which contains details regarding the schema registry, schema, compatibility mode, and other details required to register the schema with AWS Glue Schema Registry.
4. settings.xml - Maven configuration indicating where the artifact should be placed.  

<br>
<br>

## manifest.yml structure

The YAML manifest file contains information about pipeline actions. Here is the sample manifest file
```console
schema:
    file-name: customer.avsc
    region: <<region>>
    registry-name: enterprise_schemas
    schema-name: customer
    data-format: AVRO
    description: "customer schema" 
    compatibility-mode: FORWARD
    meta-tags:
        topic:
        - customer
        - salesforce_customer
        owner:
        name: "<<user-email>>"
        email: "<<user-name>>"
```

**Attribute Details:**	
1.	file-name: refers to the Avro schema file name e.g., Customer.avsc
2.	region: The AWS region in which AWS Glue Schema Registry is used e.g., us-east-1
3.	registry-name: The name of the schema registry under which the schema must be registered or exists in case of schema version update. 
4.	schema-name: The schema name with which the schema already exists or needs to be registered.
5.	data-format: Schema data format e.g., AVRO, JSON, Protobuf
6.	schema-description: User friendly description of schema for applications to understand what does the schema represents in the business context.
7.	compatibility-mode: Compatibility modes allow you to control how schemas can or cannot evolve over time. To learn more about compatibility mode, refer to the AWS documentation. 
8.	meta-tags: metadata tags can be added under meta_tags. Here you can add information such as topics, schema owners, etc.

