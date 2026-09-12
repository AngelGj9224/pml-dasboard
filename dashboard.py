"""
Paso 2 - Dashboard interactivo (Streamlit) que compara los precios PML de dos
zonas de carga a lo largo de un periodo seleccionable, leyendo desde pml.db
(generada por cargar_datos.py).

Ejecucion:
    streamlit run dashboard.py
"""

import os
import sqlite3
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import cargar_datos

RUTA_DB = "pml.db"

# Colores fijos para diferenciar zona A y zona B en todas las graficas.
COLOR_ZONA_A = "#2ca02c"  # verde
COLOR_ZONA_B = "#d62728"  # rojo


# ---------------------------------------------------------------------------
# Acceso a datos (funciones de consulta SQL, separadas de la presentacion)
# ---------------------------------------------------------------------------

@st.cache_resource
def asegurar_base_de_datos() -> None:
    """En Streamlit Community Cloud el disco es efimero (se reinicia con cada
    redeploy), asi que si pml.db no existe todavia en el contenedor, se genera
    aqui mismo a partir de los CSV incluidos en el repo. st.cache_resource
    asegura que esto corra una sola vez por sesion del servidor, no en cada
    rerun de la app."""
    if not os.path.exists(RUTA_DB):
        cargar_datos.main()


def obtener_conexion() -> sqlite3.Connection:
    return sqlite3.connect(RUTA_DB, check_same_thread=False)


@st.cache_data
def obtener_rango_fechas_disponible() -> tuple[date, date]:
    conn = obtener_conexion()
    fila = conn.execute("SELECT MIN(fecha), MAX(fecha) FROM pml_zonas_carga").fetchone()
    conn.close()
    fecha_min = date.fromisoformat(fila[0])
    fecha_max = date.fromisoformat(fila[1])
    return fecha_min, fecha_max


@st.cache_data
def obtener_zonas_disponibles() -> list[str]:
    conn = obtener_conexion()
    filas = conn.execute(
        "SELECT DISTINCT clave_zona FROM pml_zonas_carga ORDER BY clave_zona"
    ).fetchall()
    conn.close()
    return [fila[0] for fila in filas]


@st.cache_data
def obtener_precios(zona_a: str, zona_b: str, fecha_inicio: date, fecha_fin: date) -> pd.DataFrame:
    """Trae las filas (fecha, hora, zona, precio) de ambas zonas para el
    periodo seleccionado y arma una columna datetime auxiliar para graficar."""
    conn = obtener_conexion()
    df = pd.read_sql_query(
        """
        SELECT fecha, hora, clave_zona, precio_pml
        FROM pml_zonas_carga
        WHERE clave_zona IN (?, ?)
          AND fecha BETWEEN ? AND ?
        ORDER BY fecha, hora
        """,
        conn,
        params=(zona_a, zona_b, fecha_inicio.isoformat(), fecha_fin.isoformat()),
    )
    conn.close()

    # La hora en la fuente va de 1 a 24; para construir una marca de tiempo
    # valida se resta 1 (hora 24 del dia D = las 23:00 de D, fin del dia).
    df["fecha_hora"] = pd.to_datetime(df["fecha"]) + pd.to_timedelta(df["hora"] - 1, unit="h")
    return df


# ---------------------------------------------------------------------------
# Calculos / KPIs
# ---------------------------------------------------------------------------

def pivotear_por_zona(df: pd.DataFrame, zona_a: str, zona_b: str) -> pd.DataFrame:
    """Convierte el formato largo (una fila por zona-fecha-hora) a una fila
    por fecha-hora con una columna de precio por zona, para poder calcular
    el spread A - B alineado en el tiempo."""
    pivote = df.pivot_table(
        index="fecha_hora", columns="clave_zona", values="precio_pml"
    )
    pivote = pivote.rename(columns={zona_a: "precio_a", zona_b: "precio_b"})
    pivote["spread"] = pivote["precio_a"] - pivote["precio_b"]
    return pivote.reset_index()


def calcular_kpis_promedios(pivote: pd.DataFrame) -> dict:
    promedio_a = pivote["precio_a"].mean()
    promedio_b = pivote["precio_b"].mean()
    diferencia_promedio = (pivote["precio_a"] - pivote["precio_b"]).mean()
    desviacion_std_spread = pivote["spread"].std()
    return {
        "promedio_a": promedio_a,
        "promedio_b": promedio_b,
        "diferencia_promedio": diferencia_promedio,
        "desviacion_std_spread": desviacion_std_spread,
    }


# ---------------------------------------------------------------------------
# Presentacion (widgets / graficas)
# ---------------------------------------------------------------------------

def render_controles(fecha_min: date, fecha_max: date, zonas: list[str]):
    st.sidebar.header("Filtros")

    rango = st.sidebar.date_input(
        "Periodo",
        value=(fecha_min, fecha_max),
        min_value=fecha_min,
        max_value=fecha_max,
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        fecha_inicio, fecha_fin = rango
    else:
        fecha_inicio, fecha_fin = fecha_min, fecha_max

    zona_a = st.sidebar.selectbox("Zona de carga A", zonas, index=0)
    indice_b_default = 1 if len(zonas) > 1 else 0
    zona_b = st.sidebar.selectbox("Zona de carga B", zonas, index=indice_b_default)

    return zona_a, zona_b, fecha_inicio, fecha_fin


def render_grafica_precios(df: pd.DataFrame, pivote: pd.DataFrame, zona_a: str, zona_b: str):
    st.subheader("Precios del periodo")
    mostrar_spread = st.checkbox("Mostrar spread (A - B) como serie adicional", value=False)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pivote["fecha_hora"], y=pivote["precio_a"], name=zona_a, mode="lines", line=dict(color=COLOR_ZONA_A)))
    fig.add_trace(go.Scatter(x=pivote["fecha_hora"], y=pivote["precio_b"], name=zona_b, mode="lines", line=dict(color=COLOR_ZONA_B)))
    if mostrar_spread:
        fig.add_trace(
            go.Scatter(
                x=pivote["fecha_hora"], y=pivote["spread"], name=f"Spread ({zona_a} - {zona_b})",
                mode="lines", yaxis="y2", line=dict(dash="dot"),
            )
        )
        fig.update_layout(
            yaxis2=dict(title="Spread ($/MWh)", overlaying="y", side="right"),
        )
    fig.update_layout(
        xaxis_title="Fecha y hora",
        yaxis_title="Precio PML ($/MWh)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    tabla_exportable = df[["fecha", "hora", "clave_zona", "precio_pml"]].sort_values(["fecha", "hora", "clave_zona"])
    st.download_button(
        "Exportar datos a CSV",
        data=tabla_exportable.to_csv(index=False).encode("utf-8"),
        file_name="pml_comparacion.csv",
        mime="text/csv",
    )


def render_kpis_promedios(kpis: dict, zona_a: str, zona_b: str):
    st.subheader("Promedios y diferencias del periodo")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"Promedio {zona_a}", f"${kpis['promedio_a']:.2f}")
    col2.metric(f"Promedio {zona_b}", f"${kpis['promedio_b']:.2f}")
    col3.metric("Diferencia promedio (A - B)", f"${kpis['diferencia_promedio']:.2f}")
    col4.metric("Desv. estandar del spread", f"${kpis['desviacion_std_spread']:.2f}")


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Comparativo PML por Zona de Carga", layout="wide")
    st.title("Comparativo de PML por Zona de Carga")

    asegurar_base_de_datos()

    fecha_min, fecha_max = obtener_rango_fechas_disponible()
    zonas = obtener_zonas_disponibles()

    zona_a, zona_b, fecha_inicio, fecha_fin = render_controles(fecha_min, fecha_max, zonas)

    if zona_a == zona_b:
        st.warning("Selecciona dos zonas de carga distintas para comparar.")
        return
    if fecha_inicio > fecha_fin:
        st.warning("La fecha de inicio debe ser anterior o igual a la fecha final.")
        return

    df = obtener_precios(zona_a, zona_b, fecha_inicio, fecha_fin)
    if df.empty:
        st.info("No hay datos para las zonas y el periodo seleccionados.")
        return

    pivote = pivotear_por_zona(df, zona_a, zona_b)

    render_grafica_precios(df, pivote, zona_a, zona_b)
    render_kpis_promedios(calcular_kpis_promedios(pivote), zona_a, zona_b)


if __name__ == "__main__":
    main()
