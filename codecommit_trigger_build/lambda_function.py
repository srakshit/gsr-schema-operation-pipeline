from fileinput import filename
import os
from urllib import response
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


def getFileDifferences(repository_name, lastCommitId, previousCommitId):
    response = None

    if previousCommitId != None:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitId,
            afterCommitSpecifier=lastCommitId
        )
    else:
        # The case of getting initial commit (Without beforeCommitSpecifier)
        response = codecommit.get_differences(
            repositoryName=repository_name,
            afterCommitSpecifier=lastCommitId
        )

    differences = []

    if response == None:
        return differences

    while "nextToken" in response:
        response = codecommit.get_differences(
            repositoryName=repository_name,
            beforeCommitSpecifier=previousCommitId,
            afterCommitSpecifier=lastCommitId,
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


def createSchema(registryName, schemaName, dataFormat, compatibility, description, schemaDefinition, tags):
    response = gsr.create_schema(
            RegistryId={
                'RegistryName': registryName
            },
            SchemaName=schemaName,
            DataFormat=dataFormat,
            Compatibility=compatibility,
            Description=description,
            SchemaDefinition=schemaDefinition,
            Tags=tags
        )
    return response


def registerSchemaVersion(registryName, schemaName, schemaDefinition):
    response = gsr.register_schema_version(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            },
            SchemaDefinition=schemaDefinition
        )
    return response


def deleteSchemaVersion(registryName, schemaName, versions):
    response = gsr.delete_schema_versions(
            SchemaId={
                'SchemaName': schemaName,
                'RegistryName': registryName
            },
            Versions=str(versions)
        )
    return response


def registerSchemaInGsr(repoName, avroSchemaFilePath):
    doTriggerBuild = False
    
    #Read manifest.yml file
    content = getFile(repoName,MANIFEST_FILE_PATH)
    manifest_content = yaml.full_load(content)
    
    #Read avroSchema
    avroSchema = getFile(repoName,avroSchemaFilePath)
    avroSchema = json.loads(avroSchema)
    schemaDefinition = json.dumps(avroSchema)

    registryName = manifest_content['gsr']['registry']['name']
    schemaName=manifest_content['gsr']['schema']['name']
    dataFormat=manifest_content['gsr']['schema']['data_format']
    compatibility=manifest_content['gsr']['schema']['compatibility_mode']
    description=manifest_content['gsr']['schema']['description']

    metaTags = manifest_content['gsr']['meta_tags']
    tags = {}
    for key in metaTags.keys():
        if isinstance(metaTags[key], list):
            tags[key] = "/".join(metaTags[key])
        elif isinstance(metaTags[key], dict):
            for k in metaTags[key].keys():
                tags[key+"_"+k] = metaTags[key][k].replace("<<", "").replace(">>", "")
        else:
            tags[key] = metaTags[key]
    
    try:
        #Create schema first time
        createSchema(registryName, schemaName, dataFormat, compatibility, description, schemaDefinition, tags)
        print("Created new schema - " + manifest_content['gsr']['schema']['name'])
        
        #Handle malformed schema
        doTriggerBuild = True
    except gsr.exceptions.AlreadyExistsException as ex:
        #If schema already exists register a new schema version in GSR
        print("Register new schema version")
        
        registerResponse = registerSchemaVersion(registryName, schemaName, schemaDefinition)

        if registerResponse['Status'] == "AVAILABLE":
            doTriggerBuild = True
        else:
            #If failed to register schema version, delete the version
            print("Delete schema version as the version registration failed")
            delResponse = deleteSchemaVersion(registryName, schemaName, registerResponse['VersionNumber'])

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


def triggerCodeBuild(sourceVersion, region, repoName):
    build = {
        'projectName': CODE_BUILD_PROJECT,
        'sourceVersion': sourceVersion,
        'sourceTypeOverride': 'CODECOMMIT',
        'sourceLocationOverride': 'https://git-codecommit.%s.amazonaws.com/v1/repos/%s' % (region, repoName)
    }

    print("Building schema from repo %s in region %s" % (repoName, region))

    # build schema
    cb.start_build(**build)

    return


def getCommitDifferences(repoName, commitHash, branchName):
    # Get commit ID for fetching the commit log
    if (commitHash == None) or (commitHash == '0000000000000000000000000000000000000000'):
        commitHash = getLastCommitId(repoName, branchName)

    lastCommit = getLastCommitLog(repoName, commitHash)

    previousCommitId = None
    if len(lastCommit['parents']) > 0:
        previousCommitId = lastCommit['parents'][0]

    print('lastCommitId: {0} previousCommitId: {1}'.format(commitHash, previousCommitId))

    differences = getFileDifferences(repoName, commitHash, previousCommitId)

    return {
        "differences" : differences, 
        "lastCommit": lastCommit
    } 


def lambda_handler(event, context):

    # Initialize needed variables
    commitHash = event['Records'][0]['codecommit']['references'][0]['commit']
    region = event['Records'][0]['awsRegion']
    repoName = event['Records'][0]['eventSourceARN'].split(':')[-1]
    branchName = os.path.basename(str(event['Records'][0]['codecommit']['references'][0]['ref']))

    # Get differences between current and previous build.
    response = getCommitDifferences(repoName, commitHash, branchName)

    # and set flag for build triggering
    doTriggerBuild = False

    if hasPreviousBuildFailedAndNoBuildInProgress():
        # Trigger build if no build is in progress and previous build failed
        avroSchemaFilePath = getSchemaFilePath(repoName, response['lastCommit'])
        doTriggerBuild = registerSchemaInGsr(repoName, avroSchemaFilePath)
    else:
        for diff in response['differences']:
            if 'afterBlob' in diff:
                schemaFileName = os.path.basename(str(diff['afterBlob']['path']))
                avroSchemaFilePath = AVRO_FILE_PATH + schemaFileName
                # Find match for files with avro extension
                for fa in FILE_NAMES_ALLOWED:
                    if re.search(fa, schemaFileName):
                        print("Schema file %s changed!" % (schemaFileName))
                        doTriggerBuild = registerSchemaInGsr(repoName, avroSchemaFilePath)


    # Trigger codebuild job to build the repository if needed
    if doTriggerBuild:
        triggerCodeBuild(commitHash, region, repoName)

    return 'Success'