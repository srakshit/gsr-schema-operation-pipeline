from fileinput import filename
import os
import boto3
import yaml
import json
import re
from botocore.exceptions import ClientError

# Module level variables initialization
CODE_BUILD_PROJECT = os.getenv('CODE_BUILD_PROJECT')
AVRO_FILE_PATH = os.getenv('AVRO_FILE_PATH')
MANIFEST_FILE_PATH = os.getenv('MANIFEST_FILE_PATH')
FILE_NAMES_ALLOWED = ["^.*\.(avsc)$"]

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


def getLastCommitId(repository, branch="master"):
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


def registerSchemaInGsr(repoName, avroSchemaFilePath):
    doTriggerBuild = False
    
    #Read manifest.yml file
    content = getFile(repoName,MANIFEST_FILE_PATH)
    manifest_content = yaml.full_load(content)
    
    #Read avroSchema
    avroSchema = getFile(repoName,avroSchemaFilePath)
    avroSchema = json.loads(avroSchema)
    avroSchemaStr = json.dumps(avroSchema)
    
    try:
        #Create schema
        response = gsr.create_schema(
            RegistryId={
                'RegistryName': manifest_content['gsr']['registry']['name']
            },
            SchemaName=manifest_content['gsr']['schema']['name'],
            DataFormat=manifest_content['gsr']['schema']['data_format'],
            Compatibility=manifest_content['gsr']['schema']['compatibility_mode'],
            Description=manifest_content['gsr']['schema']['description'],
            SchemaDefinition=avroSchemaStr
        )
        print("Created new schema - " + manifest_content['gsr']['schema']['name'])
        
        #Handle malformed schema
        doTriggerBuild = True
    except gsr.exceptions.AlreadyExistsException as ex:
        #Register schema version in GSR
        print("Register new schema version")
        registerResponse = gsr.register_schema_version(
            SchemaId={
                'SchemaName': manifest_content['gsr']['schema']['name'],
                'RegistryName': manifest_content['gsr']['registry']['name']
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
                    'SchemaName': manifest_content['gsr']['schema']['name'],
                    'RegistryName': manifest_content['gsr']['registry']['name']
                },
                Versions=str(registerResponse['VersionNumber'])
            )
    except BaseException as ex:
        print(ex)

    return doTriggerBuild
    
def getLastBuild():
    builds = cb.list_builds_for_project(
            projectName=CODE_BUILD_PROJECT,
            sortOrder='DESCENDING'
        )
    if builds['ids']:
        return builds['ids'][0]
    return None

def getSchemaFilePath(repoName, lastCommit):
    try:
        firstCommitId = lastCommit['commitId']

        # Get first commit
        if len(lastCommit['parents']) > 0:
            firstCommitId = lastCommit['parents'][-1]

        print('First Commit ID: ' + firstCommitId)

        # Get files from first commit
        differences = getFileDifferences(repoName, firstCommitId, None)

        # Match filename with AVRO extension
        for diff in differences:
            if 'afterBlob' in diff:
                schemaFileName = os.path.basename(str(diff['afterBlob']['path']))
                avroSchemaFilePath = AVRO_FILE_PATH + schemaFileName
                
                for fa in FILE_NAMES_ALLOWED:
                    if re.search(fa, schemaFileName):
                        # Return when an avro file found
                        return avroSchemaFilePath
    
    except BaseException as ex:
        print(ex)

    return None

def hasPreviousBuildFailedAndNoBuildInProgress():
    try:
        #Get last build
        lastBuildId = getLastBuild()
        
        #Check if last build failed
        if lastBuildId is not None:
            lastBuildDetails = cb.batch_get_builds(ids=[lastBuildId])
            print(lastBuildDetails['builds'][0]['buildStatus'])
            if lastBuildDetails['builds'][0]['buildStatus'] in ['SUCCEEDED','IN_PROGRESS']:
                print("Either previous build was successful or a build is in progress!")
                return False
        
    except BaseException as ex:
        print(ex)
    
    return True

def lambda_handler(event, context):

    # Initialize needed variables
    print(event['Records'][0]['codecommit']['references'])
    commitHash = event['Records'][0]['codecommit']['references'][0]['commit']
    region = event['Records'][0]['awsRegion']
    repoName = event['Records'][0]['eventSourceARN'].split(':')[-1]
    account_id = event['Records'][0]['eventSourceARN'].split(':')[4]
    branchName = os.path.basename(
        str(event['Records'][0]['codecommit']['references'][0]['ref']))

    # Get commit ID for fetching the commit log
    if (commitHash == None) or (commitHash == '0000000000000000000000000000000000000000'):
        commitHash = getLastCommitId(repoName, branchName)

    lastCommit = getLastCommitLog(repoName, commitHash)
    print(lastCommit['parents'])
    previousCommitId = None
    if len(lastCommit['parents']) > 0:
        previousCommitId = lastCommit['parents'][0]

    print('lastCommitID: {0} previousCommitID: {1}'.format(commitHash, previousCommitId))

    differences = getFileDifferences(repoName, commitHash, previousCommitId)


    # Check whether any avro file is added/modified
    # Register the schema in GSR
    # and set flag for build triggering
    doTriggerBuild = False
    
    for diff in differences:
        if 'afterBlob' in diff:
            schemaFileName = os.path.basename(str(diff['afterBlob']['path']))
            avroSchemaFilePath = AVRO_FILE_PATH + schemaFileName

            if hasPreviousBuildFailedAndNoBuildInProgress():
                # Trigger build if no build is in progress and previous build failed
                avroSchemaFilePath = getSchemaFilePath(repoName, lastCommit)
                doTriggerBuild = registerSchemaInGsr(repoName, avroSchemaFilePath)
            else:
                # Find match for files with avro extension
                for fa in FILE_NAMES_ALLOWED:
                    print(schemaFileName)
                    if re.search(fa, schemaFileName):
                        print("Schema file changed!")
                        doTriggerBuild = registerSchemaInGsr(repoName, avroSchemaFilePath)


    # Trigger codebuild job to build the repository if needed
    if doTriggerBuild:
        build = {
            'projectName': CODE_BUILD_PROJECT,
            'sourceVersion': commitHash,
            'sourceTypeOverride': 'CODECOMMIT',
            'sourceLocationOverride': 'https://git-codecommit.%s.amazonaws.com/v1/repos/%s' % (region, repoName)
        }

        print("Building schema from repo %s in region %s" % (repoName, region))

        # build schema
        cb.start_build(**build)
    
    return 'Success.'