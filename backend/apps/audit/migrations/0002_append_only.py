from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_auditlog_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_no_change
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_append_only();
"""

REVERSE = """
DROP TRIGGER audit_auditlog_no_change ON audit_auditlog;
DROP FUNCTION audit_auditlog_append_only();
"""


class Migration(migrations.Migration):
    """Blocks UPDATE and DELETE on the audit log at the database level.

    TRUNCATE is left to privileges: the production database role should not own the table.
    """

    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
