# Comparativo de PML por Zona de Carga

Dashboard local para comparar los precios PML (Precio Marginal Local) publicados
por CENACE entre dos zonas de carga, en un periodo seleccionable.

## Requisitos

- Python 3.10+
- Dependencias en `requirements.txt`

Instalacion:

```bash
pip install -r requirements.txt
```

## Uso

### 1. Cargar los datos (`cargar_datos.py`)

Coloca los CSV de CENACE (reporte "Precios de Energia en Nodos Distribuidos
del MDA") dentro de la carpeta `PMLs_csv/`, y ejecuta:

```bash
python cargar_datos.py
```

Esto crea (o actualiza, si ya existe) la base de datos `pml.db` con la tabla
`pml_zonas_carga`. Al terminar imprime un resumen: archivos leidos, filas
insertadas/actualizadas, rango de fechas cargado y las zonas de carga
encontradas.

**Para agregar CSV nuevos:** simplemente copia los archivos adicionales a
`PMLs_csv/` y vuelve a ejecutar `python cargar_datos.py`. El script es
idempotente: usa `INSERT OR REPLACE` sobre la llave (`fecha`, `hora`,
`clave_zona`), asi que reprocesar un archivo ya cargado o corregir un archivo
existente actualiza los datos en vez de duplicarlos.

### 2. Levantar el dashboard (`dashboard.py`)

```bash
streamlit run dashboard.py
```

Se abre en el navegador. Desde la barra lateral se elige el periodo y las
dos zonas de carga a comparar; todo se recalcula automaticamente. El
dashboard muestra:

- Grafica de precios del periodo (con spread A-B opcional) y boton para
  exportar la tabla filtrada (fecha, hora, zona, precio) a CSV.
- Promedios, diferencia promedio y desviacion estandar del spread.

## Publicar en Streamlit Community Cloud

1. Sube este repositorio a GitHub (incluyendo la carpeta `PMLs_csv/`; `pml.db`
   esta en `.gitignore` porque se regenera solo).
2. En [share.streamlit.io](https://share.streamlit.io), conecta tu cuenta de
   GitHub y crea una app nueva apuntando a este repo, rama y archivo principal
   `dashboard.py`.
3. Al arrancar el proceso, `dashboard.py` corre `cargar_datos.py`
   automaticamente contra los CSV del repo antes de mostrar el dashboard
   (una sola vez por proceso, gracias a `st.cache_resource`). Como el ETL es
   idempotente, esto es seguro y asegura que la base de datos siempre
   refleje los CSV mas recientes, incluso si Community Cloud reinicia el
   proceso sin borrar el disco.

**Para actualizar los precios ya publicados:** agrega los CSV nuevos a
`PMLs_csv/` en tu copia local y sube el cambio (`git add`, `git commit`,
`git push`). Streamlit Community Cloud detecta el push y reinicia la app
sola; al reiniciar, vuelve a correr el ETL y la base de datos queda
actualizada con los CSV nuevos.

## Notas sobre el formato de los CSV de CENACE

- Las primeras 7 lineas de cada CSV son metadata del reporte (se ignoran).
- El encabezado real nombra 7 columnas, pero cada fila de datos trae 9
  valores: las 2 columnas finales no estan documentadas por CENACE y se
  descartan (no son parte del precio).
- La hora va de 1 a 24 (no de 0 a 23).
- El precio usado como `precio_pml` es la columna "Precio Zonal ($/MWh)".
- Si un archivo no tiene el encabezado esperado o alguna fila viene
  incompleta, `cargar_datos.py` lo reporta como advertencia y continua con
  el resto, sin abortar toda la carga.
