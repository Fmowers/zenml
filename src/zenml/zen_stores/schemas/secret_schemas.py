#  Copyright (c) ZenML GmbH 2022. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.
"""SQL Model Implementations for Secrets."""
import base64
import json
from datetime import datetime
from typing import Dict, Optional, cast
from uuid import UUID

from sqlalchemy import TEXT, Column
from sqlalchemy_utils.types.encrypted.encrypted_type import AesGcmEngine
from sqlmodel import Field, Relationship

from zenml.constants import TEXT_FIELD_MAX_LENGTH
from zenml.enums import SecretScope
from zenml.models import (
    SecretRequest,
    SecretResponse,
    SecretResponseBody,
    SecretResponseMetadata,
    SecretUpdate,
)
from zenml.zen_stores.schemas.base_schemas import NamedSchema
from zenml.zen_stores.schemas.schema_utils import build_foreign_key_field
from zenml.zen_stores.schemas.user_schemas import UserSchema
from zenml.zen_stores.schemas.workspace_schemas import WorkspaceSchema


class SecretSchema(NamedSchema, table=True):
    """SQL Model for secrets.

    Attributes:
        name: The name of the secret.
        values: The values of the secret.
    """

    __tablename__ = "secret"

    scope: SecretScope

    values: Optional[bytes] = Field(sa_column=Column(TEXT, nullable=True))

    workspace_id: UUID = build_foreign_key_field(
        source=__tablename__,
        target=WorkspaceSchema.__tablename__,
        source_column="workspace_id",
        target_column="id",
        ondelete="CASCADE",
        nullable=False,
    )
    workspace: "WorkspaceSchema" = Relationship(back_populates="secrets")

    user_id: UUID = build_foreign_key_field(
        source=__tablename__,
        target=UserSchema.__tablename__,
        source_column="user_id",
        target_column="id",
        ondelete="CASCADE",
        nullable=False,
    )
    user: "UserSchema" = Relationship(back_populates="secrets")

    @classmethod
    def _dump_secret_values(
        cls, values: Dict[str, str], encryption_engine: Optional[AesGcmEngine]
    ) -> bytes:
        """Dump the secret values to a string.

        Args:
            values: The secret values to dump.
            encryption_engine: The encryption engine to use to encrypt the
                secret values. If None, the values will be base64 encoded.

        Raises:
            ValueError: If the secret values do not fit in the database field.

        Returns:
            The serialized encrypted secret values.
        """
        serialized_values = json.dumps(values)

        if encryption_engine is None:
            encrypted_values = base64.b64encode(
                serialized_values.encode("utf-8")
            )
        else:
            encrypted_values = encryption_engine.encrypt(serialized_values)

        if len(encrypted_values) > TEXT_FIELD_MAX_LENGTH:
            raise ValueError(
                "Database representation of secret values exceeds max "
                "length. Please use fewer values or consider using shorter "
                "secret keys and/or values."
            )

        return encrypted_values

    @classmethod
    def _load_secret_values(
        cls,
        encrypted_values: bytes,
        encryption_engine: Optional[AesGcmEngine] = None,
    ) -> Dict[str, str]:
        """Load the secret values from a base64 encoded byte string.

        Args:
            encrypted_values: The serialized encrypted secret values.
            encryption_engine: The encryption engine to use to decrypt the
                secret values. If None, the values will be base64 decoded.

        Returns:
            The loaded secret values.
        """
        if encryption_engine is None:
            serialized_values = base64.b64decode(encrypted_values).decode()
        else:
            serialized_values = encryption_engine.decrypt(encrypted_values)

        return cast(
            Dict[str, str],
            json.loads(serialized_values),
        )

    @classmethod
    def from_request(
        cls,
        secret: SecretRequest,
    ) -> "SecretSchema":
        """Create a `SecretSchema` from a `SecretRequest`.

        Args:
            secret: The `SecretRequest` from which to create the schema.

        Returns:
            The created `SecretSchema`.
        """
        assert secret.user is not None, "User must be set for secret creation."
        return cls(
            name=secret.name,
            scope=secret.scope,
            workspace_id=secret.workspace,
            user_id=secret.user,
            # Don't store secret values implicitly in the secret. The
            # SQL secret store will call `store_secret_values` to store the
            # values separately if SQL is used as the secrets store.
            values=None,
        )

    def update(
        self,
        secret_update: SecretUpdate,
    ) -> "SecretSchema":
        """Update a `SecretSchema` from a `SecretUpdate`.

        Args:
            secret_update: The `SecretUpdate` from which to update the schema.

        Returns:
            The updated `SecretSchema`.
        """
        # Don't update the secret values implicitly in the secret. The
        # SQL secret store will call `set_secret_values` to update the
        # values separately if SQL is used as the secrets store.
        for field, value in secret_update.dict(
            exclude_unset=True, exclude={"workspace", "user", "values"}
        ).items():
            setattr(self, field, value)

        self.updated = datetime.utcnow()
        return self

    def to_model(
        self,
        hydrate: bool = False,
    ) -> SecretResponse:
        """Converts a secret schema to a secret model.

        Args:
            hydrate: Flag deciding whether to hydrate the output model(s)
                by including metadata fields in the response.

        Returns:
            The secret model.
        """
        metadata = None
        if hydrate:
            metadata = SecretResponseMetadata(
                workspace=self.workspace.to_model(),
            )

        # Don't load the secret values implicitly in the secret. The
        # SQL secret store will call `get_secret_values` to load the
        # values separately if SQL is used as the secrets store.
        body = SecretResponseBody(
            user=self.user.to_model() if self.user else None,
            created=self.created,
            updated=self.updated,
            scope=self.scope,
        )
        return SecretResponse(
            id=self.id,
            name=self.name,
            body=body,
            metadata=metadata,
        )

    def get_secret_values(
        self,
        encryption_engine: Optional[AesGcmEngine] = None,
    ) -> Dict[str, str]:
        """Get the secret values for this secret.

        This method is used by the SQL secrets store to load the secret values
        from the database.

        Args:
            encryption_engine: The encryption engine to use to decrypt the
                secret values. If None, the values will be base64 decoded.

        Returns:
            The secret values
        """
        if not self.values:
            raise KeyError(
                f"Secret values for secret {self.id} have not been stored in "
                f"the SQL secrets store."
            )
        return self._load_secret_values(self.values, encryption_engine)

    def set_secret_values(
        self,
        secret_values: Dict[str, str],
        encryption_engine: Optional[AesGcmEngine] = None,
    ) -> None:
        """Create a `SecretSchema` from a `SecretRequest`.

        This method is used by the SQL secrets store to store the secret values
        in the database.

        Args:
            secret_values: The new secret values.
            encryption_engine: The encryption engine to use to encrypt the
                secret values. If None, the values will be base64 encoded.
        """
        self.values = self._dump_secret_values(
            secret_values, encryption_engine
        )
