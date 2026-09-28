"""Migration operations for range-partitioned tables.

The column definitions come from Django's own CREATE TABLE for the model; this only adds the
partition clause, the composite primary key PostgreSQL requires, and a DEFAULT partition. The
model and the table therefore cannot drift apart.
"""

from django.db import migrations


class CreatePartitionedModel(migrations.CreateModel):
    """CreateModel, but the table is PARTITION BY RANGE (created_at) with a DEFAULT partition.

    PostgreSQL requires the partition key in the primary key, so the database key is
    (id, created_at). Django still treats `id` as the key; the identity column keeps it unique.
    The DEFAULT partition means an insert never fails because a future partition is missing.
    """

    partition_key = "created_at"

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        qn = schema_editor.quote_name
        table = model._meta.db_table
        pk_column = model._meta.pk.column

        sql, params = schema_editor.table_sql(model)
        pk_def = f"{qn(pk_column)} bigint NOT NULL PRIMARY KEY"
        if pk_def not in sql or not sql.endswith(")"):
            raise RuntimeError(f"Unexpected CREATE TABLE shape for {table}: {sql}")
        sql = sql.replace(pk_def, f"{qn(pk_column)} bigint NOT NULL", 1)
        sql = (
            f"{sql[:-1]}, PRIMARY KEY ({qn(pk_column)}, {qn(self.partition_key)}))"
            f" PARTITION BY RANGE ({qn(self.partition_key)})"
        )
        schema_editor.execute(sql, params or None)
        schema_editor.execute(
            f"CREATE TABLE {qn(table + '_default')} PARTITION OF {qn(table)} DEFAULT"
        )
        # Indexes on the parent are created on every partition, present and future.
        schema_editor.deferred_sql.extend(schema_editor._model_indexes_sql(model))

    def describe(self):
        return f"Create partitioned model {self.name}"
