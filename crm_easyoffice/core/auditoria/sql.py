"""SQL of the audit triggers (AD-08), used by core's migrations.

Migrations call these helpers with frozen arguments, so changing a list in
``core.auditoria.registro`` needs a new migration. Keep the generated SQL
stable: an old migration must produce the same triggers it always did.
"""

from __future__ import annotations

TABLA = "core_registroauditoria"
TRIGGER = "auditoria"

# Settings set by core.auditoria.contexto; empty or unset means "sistema".
_CONTEXTO = """
    usuario bigint := nullif(current_setting('app.usuario_id', true), '')::bigint;
    ip inet := nullif(current_setting('app.ip', true), '')::inet;
    origen text := coalesce(nullif(current_setting('app.origen', true), ''), 'sistema');
"""

FUNCION_REGISTRAR = f"""
CREATE FUNCTION core_auditoria_registrar() RETURNS trigger
LANGUAGE plpgsql AS $$
-- TG_ARGV: entity, excluded columns, masked columns (text[] literals).
-- INSERT stores the new row, DELETE the old one, UPDATE only the columns
-- that changed; an UPDATE that changes nothing else than updated_at or an
-- excluded column writes nothing.
DECLARE
    {_CONTEXTO}
    excluir text[] := TG_ARGV[1]::text[];
    enmascarar text[] := TG_ARGV[2]::text[];
    viejo jsonb;
    nuevo jsonb;
    anterior jsonb;
    posterior jsonb;
    clave text;
    accion text;
    registro bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        accion := 'crear';
        nuevo := to_jsonb(NEW);
        registro := (nuevo ->> 'id')::bigint;
        posterior := nuevo - excluir;
    ELSIF TG_OP = 'DELETE' THEN
        accion := 'eliminar';
        viejo := to_jsonb(OLD);
        registro := (viejo ->> 'id')::bigint;
        anterior := viejo - excluir;
    ELSE
        accion := 'modificar';
        viejo := to_jsonb(OLD);
        nuevo := to_jsonb(NEW);
        registro := (nuevo ->> 'id')::bigint;
        anterior := '{{}}'::jsonb;
        posterior := '{{}}'::jsonb;
        FOR clave IN SELECT jsonb_object_keys(nuevo) LOOP
            CONTINUE WHEN clave = 'updated_at' OR clave = ANY(excluir);
            IF (viejo -> clave) IS DISTINCT FROM (nuevo -> clave) THEN
                anterior := anterior || jsonb_build_object(clave, viejo -> clave);
                posterior := posterior || jsonb_build_object(clave, nuevo -> clave);
            END IF;
        END LOOP;
        IF posterior = '{{}}'::jsonb THEN
            RETURN NULL;
        END IF;
    END IF;
    FOREACH clave IN ARRAY enmascarar LOOP
        IF anterior ? clave THEN
            anterior := jsonb_set(anterior, ARRAY[clave], '"***"');
        END IF;
        IF posterior ? clave THEN
            posterior := jsonb_set(posterior, ARRAY[clave], '"***"');
        END IF;
    END LOOP;
    INSERT INTO {TABLA}
        (usuario_id, origen, accion, entidad, registro_id,
         valor_anterior, valor_nuevo, direccion_ip)
    VALUES
        (usuario, origen, accion, TG_ARGV[0], registro,
         anterior, posterior, ip);
    RETURN NULL;
END;
$$;
"""  # noqa: S608 - built from constants only

FUNCION_RELACION = f"""
CREATE FUNCTION core_auditoria_relacion() RETURNS trigger
LANGUAGE plpgsql AS $$
-- A many-to-many row recorded as a change of its owner.
-- TG_ARGV: owner entity, owner column, key ('rol' or 'permiso').
DECLARE
    {_CONTEXTO}
    fila jsonb;
    nombre jsonb;
    clave text := TG_ARGV[2];
BEGIN
    IF TG_OP = 'DELETE' THEN
        fila := to_jsonb(OLD);
    ELSE
        fila := to_jsonb(NEW);
    END IF;
    IF clave = 'rol' THEN
        SELECT to_jsonb(g.name) INTO nombre
        FROM auth_group g WHERE g.id = (fila ->> 'group_id')::int;
    ELSE
        SELECT to_jsonb(ct.app_label || '.' || p.codename) INTO nombre
        FROM auth_permission p
        JOIN django_content_type ct ON ct.id = p.content_type_id
        WHERE p.id = (fila ->> 'permission_id')::int;
    END IF;
    INSERT INTO {TABLA}
        (usuario_id, origen, accion, entidad, registro_id,
         valor_anterior, valor_nuevo, direccion_ip)
    VALUES
        (usuario, origen, 'modificar', TG_ARGV[0], (fila ->> TG_ARGV[1])::bigint,
         CASE WHEN TG_OP = 'DELETE' THEN jsonb_build_object(clave, nombre) END,
         CASE WHEN TG_OP = 'INSERT' THEN jsonb_build_object(clave, nombre) END,
         ip);
    RETURN NULL;
END;
$$;
"""  # noqa: S608 - built from constants only

# RF-16, RN-35: rows of the log are never changed or deleted, and the table
# is never emptied, whoever asks. The database owner can still drop these
# triggers; a role without ownership of the table is a deployment matter.
FUNCION_INMUTABLE = """
CREATE FUNCTION core_auditoria_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'El registro de auditoría no se puede modificar ni eliminar (%)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
"""

PROTEGER = f"""
CREATE TRIGGER inmutable BEFORE UPDATE OR DELETE ON {TABLA}
    FOR EACH ROW EXECUTE FUNCTION core_auditoria_inmutable();
CREATE TRIGGER sin_truncate BEFORE TRUNCATE ON {TABLA}
    FOR EACH STATEMENT EXECUTE FUNCTION core_auditoria_inmutable();
"""

CREAR_FUNCIONES = FUNCION_REGISTRAR + FUNCION_RELACION + FUNCION_INMUTABLE + PROTEGER

ELIMINAR_FUNCIONES = f"""
DROP TRIGGER IF EXISTS sin_truncate ON {TABLA};
DROP TRIGGER IF EXISTS inmutable ON {TABLA};
DROP FUNCTION IF EXISTS core_auditoria_inmutable();
DROP FUNCTION IF EXISTS core_auditoria_relacion();
DROP FUNCTION IF EXISTS core_auditoria_registrar();
"""


def _texto(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def _arreglo(valores: tuple[str, ...]) -> str:
    return _texto("{" + ",".join(valores) + "}")


def argumentos_trigger(
    entidad: str,
    excluir: tuple[str, ...],
    enmascarar: tuple[str, ...],
) -> tuple[str, str, str]:
    """The arguments as PostgreSQL stores them (``pg_trigger.tgargs``)."""
    return (entidad, "{" + ",".join(excluir) + "}", "{" + ",".join(enmascarar) + "}")


def crear_trigger(
    tabla: str,
    entidad: str,
    excluir: tuple[str, ...],
    enmascarar: tuple[str, ...],
) -> str:
    return (
        f"CREATE TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON {tabla} "
        f"FOR EACH ROW EXECUTE FUNCTION core_auditoria_registrar("
        f"{_texto(entidad)}, {_arreglo(excluir)}, {_arreglo(enmascarar)});"
    )


def crear_trigger_relacion(tabla: str, entidad: str, columna: str, clave: str) -> str:
    return (
        f"CREATE TRIGGER {TRIGGER} AFTER INSERT OR DELETE ON {tabla} "
        f"FOR EACH ROW EXECUTE FUNCTION core_auditoria_relacion("
        f"{_texto(entidad)}, {_texto(columna)}, {_texto(clave)});"
    )


def eliminar_trigger(tabla: str) -> str:
    return f"DROP TRIGGER IF EXISTS {TRIGGER} ON {tabla};"
