"""A stay cannot be allotted to a room that is out of service, and a room cannot be taken out of
service over a stay that is allotted to it.

The two facts live in different tables, so one exclusion constraint cannot cover them. Each table gets
a trigger that locks the room's row first. That makes an allotment and a block for the same room wait
for each other, so the second of the two always sees what the first one wrote.
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION booking_room_not_blocked() RETURNS trigger AS $$
BEGIN
    IF NEW.room_id IS NOT NULL AND NEW.status IN ('ALLOTTED', 'CHECKED_IN') THEN
        PERFORM 1 FROM rooms_room WHERE id = NEW.room_id FOR NO KEY UPDATE;
        IF EXISTS (
            SELECT 1 FROM rooms_roomblock b
            WHERE b.room_id = NEW.room_id
              AND daterange(b.starts_on, b.ends_on, '[)') && daterange(NEW.check_in, NEW.check_out, '[)')
        ) THEN
            RAISE EXCEPTION 'room_not_blocked: the room is out of service on these dates'
                USING ERRCODE = 'exclusion_violation', CONSTRAINT = 'room_not_blocked';
        END IF;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER booking_room_not_blocked
    BEFORE INSERT OR UPDATE OF room_id, check_in, check_out, status ON bookings_booking
    FOR EACH ROW EXECUTE FUNCTION booking_room_not_blocked();

CREATE FUNCTION block_not_over_stay() RETURNS trigger AS $$
BEGIN
    PERFORM 1 FROM rooms_room WHERE id = NEW.room_id FOR NO KEY UPDATE;
    IF EXISTS (
        SELECT 1 FROM bookings_booking k
        WHERE k.room_id = NEW.room_id
          AND k.status IN ('ALLOTTED', 'CHECKED_IN')
          AND daterange(k.check_in, k.check_out, '[)') && daterange(NEW.starts_on, NEW.ends_on, '[)')
    ) THEN
        RAISE EXCEPTION 'block_not_over_stay: a stay is allotted to the room on these dates'
            USING ERRCODE = 'exclusion_violation', CONSTRAINT = 'block_not_over_stay';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER block_not_over_stay
    BEFORE INSERT OR UPDATE OF room_id, starts_on, ends_on ON rooms_roomblock
    FOR EACH ROW EXECUTE FUNCTION block_not_over_stay();
"""

REVERSE = """
DROP TRIGGER block_not_over_stay ON rooms_roomblock;
DROP FUNCTION block_not_over_stay();
DROP TRIGGER booking_room_not_blocked ON bookings_booking;
DROP FUNCTION booking_room_not_blocked();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0002_date_changes"),
        ("rooms", "0002_room_blocks"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
