"""IGN Géoplateforme endpoints — single source of truth for URLs."""

GEOPLATEFORME_WFS = "https://data.geopf.fr/wfs/ows"
GEOPLATEFORME_WMS = "https://data.geopf.fr/wms-r/wms"
LIDAR_HD_BASE_URL = "https://data.geopf.fr/telechargement/download/LiDARHD-NUALID"

BDTOPO_BATIMENT_LAYER = "BDTOPO_V3:batiment"
LIDAR_HD_DALLE_LAYER = "IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle"
# HR = 20cm/pixel national (BD ORTHO standard, France entière)
ORTHO_HR_LAYER = "HR.ORTHOIMAGERY.ORTHOPHOTOS"
# THR = 5cm/pixel urban (BD ORTHO Très Haute Résolution, IDF + grandes métropoles)
ORTHO_THR_LAYER = "THR.ORTHOIMAGERY.ORTHOPHOTOS"
