import urllib.request


def metadatos_instancia():
    # IMDSv2: sin proxy, sin reintentos y con tiempo de espera corto fuera de EC2.
    base = "http://169.254.169.254/latest/"
    resultado = {"instance_id": None, "zona_disponibilidad": None}
    cliente = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        peticion = urllib.request.Request(base + "api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        with cliente.open(peticion, timeout=0.3) as respuesta:
            token = respuesta.read().decode()
        for clave, ruta in (("instance_id", "instance-id"), ("zona_disponibilidad", "placement/availability-zone")):
            peticion = urllib.request.Request(base + "meta-data/" + ruta,
                headers={"X-aws-ec2-metadata-token": token})
            with cliente.open(peticion, timeout=0.3) as respuesta:
                resultado[clave] = respuesta.read().decode()
    except (OSError, ValueError):
        pass
    return resultado
