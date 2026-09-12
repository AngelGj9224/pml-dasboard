"""
Paso 1 - ETL: lee los CSV de precios PML publicados por CENACE (carpeta PMLs_csv/)
y los carga en la base de datos SQLite local pml.db.

Ejecucion:
    python cargar_datos.py

Se puede ejecutar repetidamente (por ejemplo cada vez que se agregan CSV nuevos
a la carpeta) sin generar filas duplicadas ni romperse si vuelve a leer un
archivo ya procesado (ver INSERT OR REPLACE en cargar_dataframe_a_db).
"""

import csv
import glob
import os
import sqlite3
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

CARPETA_CSV = "PMLs_csv"
RUTA_DB = "pml.db"

# Los CSV de CENACE inspeccionados para este proyecto (reporte "Precios de
# Energia en Nodos Distribuidos del MDA", Sistema Interconectado Nacional)
# NO mezclan nodos ni zonas de generacion: la columna "Zona de Carga" solo
# contiene nombres de zona (ACAPULCO, GUADALAJARA, MONTERREY, etc.), nunca
# claves numericas de nodo. Aun asi, dejamos el criterio de filtrado como
# funcion configurable (ver es_zona_de_carga_valida) para que, si algun CSV
# futuro sí trae otro tipo de entidad mezclada, sea facil excluirla: el
# criterio usado es que una zona de carga valida es un texto no vacio que no
# luce como una clave numerica de nodo (los nodos de CENACE se identifican
# con claves alfanumericas cortas tipo "01ACA-115", muy distintas de un
# nombre de zona como "ACAPULCO").
def es_zona_de_carga_valida(clave: str) -> bool:
    clave = clave.strip()
    if not clave:
        return False
    # Una clave de nodo tipica trae digitos y guiones (p.ej. "01ACA-115");
    # una zona de carga es un nombre en texto plano.
    if any(c.isdigit() for c in clave) or "-" in clave:
        return False
    return True


# Numero de lineas de metadata de CENACE antes del encabezado real de la
# tabla (nombre del reporte, mes, fecha de descarga, nota de acentos, etc.).
# Confirmado inspeccionando los CSV reales de PMLs_csv.
LINEAS_METADATA = 7

# Los CSV traen un encabezado con 7 columnas nombradas, pero cada fila de
# datos trae 9 valores: las ultimas 2 columnas no estan documentadas por
# CENACE (valores "0"/"1" observados, aparentan ser flags internos) y no se
# usan para el dashboard, asi que se leen por posicion y se ignoran.
COL_FECHA = 0
COL_HORA = 1
COL_ZONA = 2
COL_PRECIO_ZONAL = 3
MIN_COLUMNAS_ESPERADAS = 4  # hasta precio_pml inclusive; el resto se ignora


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def crear_esquema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pml_zonas_carga (
            fecha       TEXT NOT NULL,
            hora        INTEGER NOT NULL,
            clave_zona  TEXT NOT NULL,
            precio_pml  REAL NOT NULL,
            PRIMARY KEY (fecha, hora, clave_zona)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archivos_procesados (
            nombre_archivo TEXT PRIMARY KEY,
            fecha_carga    TEXT NOT NULL,
            filas_leidas   INTEGER NOT NULL
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Lectura y parseo de un CSV
# ---------------------------------------------------------------------------

def leer_filas_zona_carga(ruta_csv: str) -> list[tuple[str, int, str, float]]:
    """Lee un CSV de CENACE y devuelve las filas (fecha, hora, clave_zona,
    precio_pml) que correspondan a zonas de carga. Filas con formato
    inesperado se saltan con una advertencia, sin abortar el archivo completo.
    """
    filas: list[tuple[str, int, str, float]] = []

    with open(ruta_csv, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        todas_las_lineas = list(reader)

    if len(todas_las_lineas) <= LINEAS_METADATA + 1:
        print(f"  [ADVERTENCIA] {ruta_csv}: archivo demasiado corto, se omite.")
        return filas

    encabezado = todas_las_lineas[LINEAS_METADATA]
    primera_col = encabezado[0].strip().lower() if encabezado else ""
    if primera_col != "fecha":
        print(
            f"  [ADVERTENCIA] {ruta_csv}: no se encontro el encabezado 'Fecha' "
            f"en la linea {LINEAS_METADATA + 1} (se encontro {encabezado!r}); "
            "se omite el archivo."
        )
        return filas

    lineas_datos = todas_las_lineas[LINEAS_METADATA + 1:]

    for num_linea, fila in enumerate(lineas_datos, start=LINEAS_METADATA + 2):
        if not fila or all(not c.strip() for c in fila):
            continue
        if len(fila) < MIN_COLUMNAS_ESPERADAS:
            print(
                f"  [ADVERTENCIA] {ruta_csv} linea {num_linea}: solo "
                f"{len(fila)} columnas (se esperaban >= {MIN_COLUMNAS_ESPERADAS}), se omite."
            )
            continue

        clave_zona = fila[COL_ZONA].strip()
        if not es_zona_de_carga_valida(clave_zona):
            continue

        try:
            fecha = fila[COL_FECHA].strip()
            hora = int(fila[COL_HORA].strip())
            precio_pml = float(fila[COL_PRECIO_ZONAL].strip())
        except ValueError:
            print(
                f"  [ADVERTENCIA] {ruta_csv} linea {num_linea}: no se pudo "
                f"convertir fecha/hora/precio ({fila[:4]}), se omite."
            )
            continue

        filas.append((fecha, hora, clave_zona, precio_pml))

    return filas


# ---------------------------------------------------------------------------
# Carga idempotente a la base de datos
# ---------------------------------------------------------------------------

def cargar_filas_a_db(conn: sqlite3.Connection, filas: list[tuple[str, int, str, float]]) -> int:
    """Inserta o reemplaza filas usando la llave primaria (fecha, hora,
    clave_zona), de modo que reprocesar un archivo o cargar una correccion de
    CENACE actualiza el dato en vez de duplicarlo."""
    conn.executemany(
        """
        INSERT OR REPLACE INTO pml_zonas_carga (fecha, hora, clave_zona, precio_pml)
        VALUES (?, ?, ?, ?)
        """,
        filas,
    )
    conn.commit()
    return len(filas)


def registrar_archivo_procesado(conn: sqlite3.Connection, nombre_archivo: str, filas_leidas: int) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO archivos_procesados (nombre_archivo, fecha_carga, filas_leidas)
        VALUES (?, ?, ?)
        """,
        (nombre_archivo, datetime.now().isoformat(timespec="seconds"), filas_leidas),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Orquestacion principal
# ---------------------------------------------------------------------------

def main() -> None:
    rutas_csv = sorted(glob.glob(os.path.join(CARPETA_CSV, "*.csv")))
    if not rutas_csv:
        print(f"No se encontraron archivos CSV en '{CARPETA_CSV}/'.")
        return

    conn = sqlite3.connect(RUTA_DB)
    crear_esquema(conn)

    cursor = conn.execute("SELECT nombre_archivo FROM archivos_procesados")
    archivos_ya_procesados = {fila[0] for fila in cursor.fetchall()}

    archivos_nuevos = []
    archivos_reprocesados = []
    total_filas_insertadas = 0
    zonas_encontradas: set[str] = set()
    fechas_encontradas: set[str] = set()

    for ruta_csv in rutas_csv:
        nombre_archivo = os.path.basename(ruta_csv)
        filas = leer_filas_zona_carga(ruta_csv)

        if not filas:
            print(f"[SIN DATOS] {nombre_archivo}: 0 filas de zona de carga validas.")
            continue

        cargar_filas_a_db(conn, filas)
        registrar_archivo_procesado(conn, nombre_archivo, len(filas))

        if nombre_archivo in archivos_ya_procesados:
            archivos_reprocesados.append(nombre_archivo)
        else:
            archivos_nuevos.append(nombre_archivo)

        total_filas_insertadas += len(filas)
        zonas_encontradas.update(fila[2] for fila in filas)
        fechas_encontradas.update(fila[0] for fila in filas)

        print(f"[OK] {nombre_archivo}: {len(filas)} filas procesadas.")

    conn.close()

    print("\n" + "=" * 60)
    print("RESUMEN DE CARGA")
    print("=" * 60)
    print(f"Archivos leidos:        {len(rutas_csv)}")
    print(f"  - nuevos:              {len(archivos_nuevos)}")
    print(f"  - ya cargados (actualizados): {len(archivos_reprocesados)}")
    print(f"Filas insertadas/actualizadas: {total_filas_insertadas}")
    if fechas_encontradas:
        print(f"Rango de fechas cargado: {min(fechas_encontradas)} a {max(fechas_encontradas)}")
    print(f"Zonas de carga distintas ({len(zonas_encontradas)}):")
    for zona in sorted(zonas_encontradas):
        print(f"  - {zona}")


if __name__ == "__main__":
    main()
