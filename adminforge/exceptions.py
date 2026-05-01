class AdminForgeError(Exception):
    pass


class JaExiste(AdminForgeError):
    pass


class NaoExiste(AdminForgeError):
    pass


class FormatoInvalido(AdminForgeError):
    pass


class EstadoInvalido(AdminForgeError):
    pass


class LockOcupado(AdminForgeError):
    pass


class CadeiaQuebrada(AdminForgeError):
    pass


class HostKeyDivergente(AdminForgeError):
    pass


class CanceladoPeloUsuario(AdminForgeError):
    pass
