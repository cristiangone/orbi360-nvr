# Modelo OpenVINO precompilado

`ssdlite_mobilenet_v2.xml` / `.bin` es el modelo de deteccion por defecto
(SSDLite MobileNet v2 COCO, del TensorFlow Object Detection Model Zoo, licencia
Apache 2.0) convertido a OpenVINO IR con `docker/main/build_ov_model.py` y
`docker/main/requirements-ov.txt` (OpenVINO 2026.4) en Debian 12.

`orbi360/lxc/install.sh` intenta convertirlo en el propio equipo, igual que el
Dockerfile, y usa esta copia solo si la conversion falla (en algunas CPU
OpenVINO aborta con `free(): invalid next size`).

Para regenerarlo, repetir la conversion y reemplazar ambos archivos.
