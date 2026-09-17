from pydantic import BaseModel


class UserIdentity(BaseModel):
    principalId: str


class RequestParameters(BaseModel):
    accessKey: str | None = None
    region: str | None = None
    sourceIPAddress: str | None = None


class MinioResponseElements(BaseModel):
    x_amz_request_id: str | None = None
    x_minio_deployment_id: str | None = None
    x_minio_origin_endpoint: str | None = None


class S3BucketOwner(BaseModel):
    principalId: str


class S3Bucket(BaseModel):
    name: str
    ownerIdentity: S3BucketOwner
    arn: str


class S3Object(BaseModel):
    key: str
    size: int | None = None
    eTag: str | None = None
    contentType: str | None = None
    versionId: str | None = None
    sequencer: str | None = None


class S3(BaseModel):
    s3SchemaVersion: str
    configurationId: str
    bucket: S3Bucket
    object: S3Object


class S3Record(BaseModel):
    eventVersion: str
    eventSource: str
    awsRegion: str
    eventTime: str
    eventName: str
    userIdentity: UserIdentity
    requestParameters: RequestParameters
    responseElements: MinioResponseElements
    s3: S3


class MinIOEvent(BaseModel):
    """Full MinIO bucket notification event payload."""

    EventName: str
    Key: str
    Records: list[S3Record]
