from fileinput import filename
import os
import boto3
import yaml
import json
from botocore.exceptions import ClientError

# Module level variables initialization
CODE_BUILD_PROJECT = os.getenv('CODE_BUILD_PROJECT')

codecommit = boto3.client('codecommit')
cb = boto3.client('codebuild')
gsr = boto3.client('glue')


def getLastCommitLog(repository, commitId):
    response = codecommit.get_commit(
        repositoryName=repository,
        commitId=commitId
    )
    return response['commit']


def getFileDifferences(repository_name, lastCommitID, previousCommitID):
    response = None

    if previousCommitID != None:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitID,
            afterCommitSpecifier=lastCommitID
        )
    else:
        # The case of getting initial commit (Without beforeCommitSpecifier)
        response = codecommit.get_differences(
            repositoryName=repository_name,
            afterCommitSpecifier=lastCommitID
        )

    differences = []

    if response == None:
        return differences

    while "nextToken" in response:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitID,
            afterCommitSpecifier=lastCommitID,
            nextToken=response["nextToken"]
        )
        differences += response.get("differences", [])
    else:
        differences += response["differences"]

    return differences


def getLastCommitID(repository, branch="master"):
    response = codecommit.get_branch(
        repositoryName=repository,
        branchName=branch
    )
    commitId = response['branch']['commitId']
    return commitId


def getFile(repository, filePath, branch="master"):
    response = codecommit.get_file(
                repositoryName=repository,
                commitSpecifier=branch,
                filePath=filePath
            )
    content = response['fileContent']
    return content


def registerSchemaInGsr(repoName, fileName):
    doTriggerBuild = False

    #Read manifest.yml file
    content = getFile(repoName,fileName)
    documents = yaml.full_load(content)

    schemaBasePath = documents['schema']['path']
    schemaVersion = documents['schema']['version']
    schemaFileName = documents['schema']['file_name']

    
    #Build latest avro schema filePath    
    avroSchemaFilePath = '%s%s/%s' % (schemaBasePath, schemaVersion, schemaFileName)
    
    #Read avroSchema
    avroSchema = getFile(repoName,avroSchemaFilePath)
    avroSchema = json.loads(avroSchema)
    avroSchemaStr = json.dumps(avroSchema)
    print(avroSchemaStr)
    
    try:
        #Create schema
        response = gsr.create_schema(
            RegistryId={
                'RegistryName': documents['gsr']['registry']['name']
            },
            SchemaName=documents['gsr']['schema']['name'],
            DataFormat='AVRO',
            Compatibility='FORWARD',
            Description=documents['gsr']['schema']['description'],
            SchemaDefinition=avroSchemaStr
        )
        print("Created new schema - " + documents['gsr']['schema']['name'])
        
        #Handle malformed schema
        doTriggerBuild = True
    except:
        #Register schema version in GSR
        print("Register new schema version")
        registerResponse = gsr.register_schema_version(
            SchemaId={
                'SchemaName': documents['gsr']['schema']['name'],
                'RegistryName': documents['gsr']['registry']['name']
            },
            SchemaDefinition=avroSchemaStr
        )

        if registerResponse['Status'] == "AVAILABLE":
            doTriggerBuild = True
        else:
            #If failed to register schema version, delete the version
            print("Delete schema version as the version registration failed")
            delResponse = gsr.delete_schema_versions(
                SchemaId={
                    'SchemaName': documents['gsr']['schema']['name'],
                    'RegistryName': documents['gsr']['registry']['name']
                },
                Versions=str(registerResponse['VersionNumber'])
            )

    return doTriggerBuild

def lambda_handler(event, context):

    # Initialize needed variables
    file_extension_allowed = [".yml", "yaml"]
    fileNames_allowed = ["manifest"]
    commit_hash = event['Records'][0]['codecommit']['references'][0]['commit']
    region = event['Records'][0]['awsRegion']
    repo_name = event['Records'][0]['eventSourceARN'].split(':')[-1]
    account_id = event['Records'][0]['eventSourceARN'].split(':')[4]
    branchName = os.path.basename(
        str(event['Records'][0]['codecommit']['references'][0]['ref']))

    # Get commit ID for fetching the commit log
    if (commit_hash == None) or (commit_hash == '0000000000000000000000000000000000000000'):
        commit_hash = getLastCommitID(repo_name, branchName)

    lastCommit = getLastCommitLog(repo_name, commit_hash)

    previousCommitID = None
    if len(lastCommit['parents']) > 0:
        previousCommitID = lastCommit['parents'][0]

    print('lastCommitID: {0} previousCommitID: {1}'.format(
        commit_hash, previousCommitID))

    differences = getFileDifferences(repo_name, commit_hash, previousCommitID)
    print(differences)


    # Check whether specific file or specific extension file is added/modified
    # Register the schema in GSR
    # and set flag for build triggering
    doTriggerBuild = False
    for diff in differences:
        if 'afterBlob' in diff:
            root, extension = os.path.splitext(str(diff['afterBlob']['path']))
            fileName = os.path.basename(str(diff['afterBlob']['path']))
            if ((extension in file_extension_allowed) or (fileName in fileNames_allowed)):
                # Register schema in GSR
                doTriggerBuild = registerSchemaInGsr(repo_name, fileName)


    # Trigger codebuild job to build the repository if needed
    if doTriggerBuild:
        build = {
            'projectName': CODE_BUILD_PROJECT,
            'sourceVersion': commit_hash,
            'sourceTypeOverride': 'CODECOMMIT',
            'sourceLocationOverride': 'https://git-codecommit.%s.amazonaws.com/v1/repos/%s' % (region, repo_name)
        }

        print("Building schema from repo %s in region %s" % (repo_name, region))

        # build schema
        cb.start_build(**build)
    else:
        print('Changed files does not match any triggers. Hence build is suppressed')
    
    return 'Success.'
