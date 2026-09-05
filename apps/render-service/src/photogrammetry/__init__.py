"""Photogrammétrie pipeline ArchiClaude — IGN open data based.

Reconstruction 3D contexte quartier depuis :
- IGN LiDAR HD (LAZ classifié, Etalab 2.0)
- IGN BD TOPO V3 (footprints + heights LOD2 via geom 3D, Etalab 2.0)
- IGN BD ORTHO 20cm (textures aériennes, Etalab 2.0)
- OSM (routes, mobilier, arbres, ODbL)

Verifications Jour 1 dérisquage 2026-06-03 :
- BD TOPO V3 batiment WFS répond avec géom 3D LOD2 (z dans vertices)
- LiDAR HD dalle Nogent (LHD_FXX_0661_6860) classifiée, 128 MB COPC
- BD ORTHO 20cm WMS répond image 512x512 JPEG en <1s

Voir ArchiBrain : '3 Resources/Tech/Pipeline 3D contexte quartier — IGN LiDAR HD.md'
"""

from .ign_endpoints import (
    GEOPLATEFORME_WFS,
    GEOPLATEFORME_WMS,
    LIDAR_HD_BASE_URL,
    BDTOPO_BATIMENT_LAYER,
    LIDAR_HD_DALLE_LAYER,
    ORTHO_HR_LAYER,
)

__all__ = [
    "GEOPLATEFORME_WFS",
    "GEOPLATEFORME_WMS",
    "LIDAR_HD_BASE_URL",
    "BDTOPO_BATIMENT_LAYER",
    "LIDAR_HD_DALLE_LAYER",
    "ORTHO_HR_LAYER",
]
