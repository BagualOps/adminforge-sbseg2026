# AdminForge

Sistema de linha de comando para gerenciar contas de administradores em frotas de servidores Linux (~600 máquinas, ~20 admins).

A proposta é evitar ferramentas pesadas como FreeIPA ou LDAP, usar poucas dependências, manter histórico completo do que o operador faz e oferecer auditoria operacional sob demanda para inspecionar usuários e serviços presentes em cada servidor.

## Princípios

- **Modular.** Partes com responsabilidades claras, cada uma substituível.
- **Independente em tempo de uso.** Configuração aplicada, servidor funciona sozinho.
- **Só CLI.** Sem interface gráfica na v1.
- **Registra tudo, com resultado.** Cada ação do Superadmin fica no histórico.
- **Só aplica o que mudou.** O sistema sabe o que já está em cada servidor.
- **Inspeciona o real sob demanda.** Compara configuração declarada com realidade operacional.

## Arquitetura

Seis componentes:

| Componente | Responsabilidade |
|------------|------------------|
| **CLI**      | Lê o comando, valida sintaxe, chama o Núcleo, imprime resultado. |
| **Núcleo**   | Aplica regras de negócio. Coordena Store, Planner, Deployer e Auditor. |
| **Store**    | Persiste entidades em arquivos YAML (escrita atômica + lockfile). |
| **Planner**  | Compara estado desejado com `chaves_instaladas` e produz lista de subações. |
| **Deployer** | Executa subações via SSH. Também faz inspeção operacional somente leitura. |
| **Auditor**  | Persiste histórico append-only (cadeia de hashes). |

## Modelo de dados

Sete entidades: `Admin`, `CredencialSSH`, `GrupoAdmin`, `Servidor`, `GrupoServidor`, `Permissao`, `Historico`.

Regra central: um admin só acessa um servidor se ambos estiverem em grupos ligados por uma permissão.

## Persistência

```
state/
├── admins/             # um arquivo por admin
├── admin-groups/
├── servers/            # cada server.yaml inclui chaves_instaladas
├── server-groups/
├── permissions.yaml
├── history.jsonl       # histórico (append-only)
└── .lock               # evita escrita simultânea
```

## Casos de uso (v1)

| ID    | Comando                                |
|-------|----------------------------------------|
| UC-1  | `adminforge admin add`                 |
| UC-2  | `adminforge key add`                   |
| UC-3  | `adminforge group ...`                 |
| UC-4  | `adminforge server add`                |
| UC-5  | `adminforge server-group ...`          |
| UC-6  | `adminforge grant` / `revoke`          |
| UC-7  | `adminforge preview`                   |
| UC-8  | `adminforge apply`                     |
| UC-9  | `adminforge history ...`               |
| UC-10 | `adminforge audit server`              |

## Roadmap

- **M-0** Validar a modelagem (revisão com Rui e Diego). _Atual._
- **M-1** Protótipo mínimo em Python: cadastros, prévia, apply.
- **M-2** Robustez: retentativa, reconciliação opcional (`apply verify`), auditoria operacional, cifragem seletiva.
- **M-3** Porta para Rust e modo *pull* (servidores puxam estado de repositório Git assinado).

## Documentação

Modelagem detalhada (papéis, casos de uso, fluxos, cuidados de segurança, questões em aberto): [`docs/modelagem-v1.pdf`](docs/modelagem-v1.pdf).

## Autor

Cristhian Kapelinski — Porto Alegre, abril de 2026.
