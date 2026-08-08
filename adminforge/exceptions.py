"""Exception hierarchy for AdminForge's core (`core.nucleo`), planner, store
and deployer layers. All are caught at the operation boundary in
`core.nucleo` and turned into a failed `domain.Operacao` rather than
propagating raw, so the CLI and audit log always see a domain-level error.
"""


class AdminForgeError(Exception):
    """Base class for every error AdminForge raises intentionally.

    Catch this (rather than `Exception`) at call sites that want to
    distinguish "an expected, domain-level failure" from a genuine bug.
    """

    pass


class JaExiste(AdminForgeError):
    """A create/rename operation targets a name that is already in use.

    Raised for usernames, hostnames, group names and sudo-profile names
    alike; there is no per-entity subclass, so callers that need to know
    which entity collided must rely on the message text.
    """

    pass


class NaoExiste(AdminForgeError):
    """A lookup by name/id (user, server, group, sudo-profile, credential,
    operation) found nothing.

    Mirrors `JaExiste`: one exception class covers every entity type.
    """

    pass


class FormatoInvalido(AdminForgeError):
    """User-supplied input failed validation before anything was persisted
    or sent to a server (e.g. a malformed username, email, hostname, IPv4,
    SSH key or sudo command).

    Raised synchronously during validation, so callers can assume no
    partial state was written when this is caught.
    """

    pass


class EstadoInvalido(AdminForgeError):
    """The requested change is well-formed but conflicts with the current
    state (e.g. deleting a group that still has permissions attached, or a
    sudo-profile that is still referenced by a grant).

    Distinguishes this class of error from `FormatoInvalido`: the input
    itself was fine, the *system* is not in a state where it can be
    applied yet.
    """

    pass


class LockOcupado(AdminForgeError):
    """Another AdminForge process already holds the store's lock.

    Signals contention, not corruption: the caller is expected to retry
    later rather than treat the store as broken.
    """

    pass


class CadeiaQuebrada(AdminForgeError):
    """The auditor's hash chain does not verify: some entry's
    `hash`/`hash_anterior` does not match what was recomputed from its
    content, or the sequence of `hash_anterior` values is discontinuous.

    Raised by `interfaces.auditor.IAuditor.verificar_cadeia`; signals that
    the audit log may have been tampered with or corrupted, not a routine
    validation failure.
    """

    pass


class HostKeyDivergente(AdminForgeError):
    """A server's SSH host key is missing or does not match what was
    pinned in `domain.Servidor.chave_host`.

    Raised before any write to the server, since deploying against an
    unverified host key would defeat the point of pinning it in the first
    place.
    """

    pass


class CanceladoPeloUsuario(AdminForgeError):
    """An interactive confirmation was declined.

    Not currently raised anywhere in this codebase; kept for callers
    (e.g. a future or external CLI front-end) that want a dedicated
    exception type for "the operator said no", distinct from a genuine
    validation or state error.
    """

    pass
