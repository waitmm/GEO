"""User-reported asset checks, frozen in an execution revision, never source facts."""
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError


class AssetVerification(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    asset_type: str = Field(min_length=1, max_length=80)
    publication_surface: str = Field(min_length=1, max_length=100)
    inventory_scope: str = Field(min_length=1, max_length=1000)
    inventory_complete: StrictBool = False
    no_suitable_existing: StrictBool = False
    url: str = Field(default='', max_length=2000)
    title: str = Field(default='', max_length=300)
    content_version: str = Field(default='', max_length=300)
    ownership_basis: str = Field(default='', max_length=1000)
    editable: StrictBool = False
    content_fit: StrictBool = False


def asset_check_errors(selection: dict) -> list[str]:
    operation = selection.get('asset_operation')
    if operation == 'CONDITIONAL':
        return ['FINAL_ASSET_OPERATION_REQUIRED']
    if operation not in {'CREATE_NEW', 'UPDATE_EXISTING'}:
        return ['ASSET_OPERATION_SELECTION_REQUIRED']
    try:
        check = AssetVerification.model_validate(selection.get('asset_verification'))
    except ValidationError:
        return ['ASSET_VERIFICATION_REQUIRED']
    if check.asset_type != selection.get('asset_type') or check.publication_surface != selection.get('publication_surface'):
        return ['ASSET_VERIFICATION_SCOPE_MISMATCH']
    if operation == 'CREATE_NEW':
        return [] if check.inventory_complete and check.no_suitable_existing and not check.url else ['ASSET_INVENTORY_INCOMPLETE']
    try:
        url = urlsplit(check.url)
        valid_url = (url.scheme in {'http', 'https'} and bool(url.hostname) and not url.username
                     and not url.password and not any(c.isspace() for c in check.url))
        url.port
    except ValueError:
        valid_url = False
    if not (valid_url and check.title and check.content_version and check.ownership_basis
            and check.editable and check.content_fit and not check.no_suitable_existing):
        return ['MANAGED_ASSET_REQUIRED_FOR_UPDATE']
    return []
