# concursos-sp

Mapa de concursos públicos com lotação no estado de São Paulo: os que estão com inscrições abertas e os que ainda estão em preparação (autorizados ou com banca em contratação).

Página: https://profcaiodaniel.github.io/concursos-sp/

## Como funciona

Um coletor em Python roda no GitHub Actions às segundas e quintas, lê as fontes abaixo, junta tudo numa base única sem duplicatas e publica a página. Aos domingos, uma revisão assistida lê os editais novos e preenche o que um programa não extrai com segurança: descrição, cronograma completo e regras para pessoas com deficiência.

| Fonte | Para quê |
|---|---|
| PCI Concursos | Descobrir concursos abertos (seção SP e nacional) |
| Concursos no Brasil | Checagem cruzada do primeiro agregador |
| Nosso Rumo, Instituto Mais | Bancas com listagem pública: confirmam datas na fonte primária |
| PNCP | Contratação da banca organizadora, que antecede o edital |
| Diário Oficial do Estado de SP | Atos que autorizam concurso na esfera estadual |
| Querido Diário | Diários oficiais municipais (quando a API responde) |
| IBGE/SIDRA | População dos 645 municípios |

As fontes testadas que não puderam ser usadas, e o motivo, estão em `dados/fontes_testadas.json` e na aba Cobertura da página.

## Regras da base

Nenhum registro entra sem link para a fonte. "Autorizado" exige ato oficial publicado; notícia de imprensa ou de cursinho não conta. Campo que não pôde ser extraído com segurança fica vazio e listado em `a_conferir`, nunca preenchido por estimativa. O coletor respeita o `robots.txt` de cada site, espera entre requisições e se identifica no cabeçalho `User-Agent`. Quando uma fonte falha, a falha aparece na página.

Estágios, residências e vestibulares ficam fora. Processos seletivos entram marcados como tal e ficam ocultos por padrão.

## Limites conhecidos

A fase anterior ao edital só é visível onde o município publica em fonte legível por programa. Municípios com até 20 mil habitantes têm prazo legal até abril de 2027 para adotar o PNCP; os que ainda não publicam lá aparecem como "sem cobertura" na página. Concursos feitos por comissão própria, sem banca contratada, não deixam rastro no PNCP.

As autorizações federais não são coletadas automaticamente, porque o portal do Diário Oficial da União recusa acesso automatizado. Elas entram pela revisão semanal, em `dados/manual.json`.

A maior banca do estado (Vunesp) e outras sete bloqueiam acesso automatizado. Para esses concursos, a descoberta vem dos agregadores, e o link primário aponta para o site da banca.

## Estrutura

```
coletor/            código do coletor
  fontes/           um módulo por fonte
  classificar.py    esfera, município e chave de comparação entre fontes
  extrair.py        datas, taxa, site e cargos a partir de texto
  main.py           consolidação e gravação
dados/              base publicada (JSON)
  concursos.json    registros
  cobertura.json    situação de cada município
  fontes.json       resultado da última coleta, fonte por fonte
  enriquecimento.json  descrição, cronograma e regras PcD conferidos no edital
  manual.json       registros incluídos na revisão semanal
site/index.html     página
probe/              scripts da sondagem inicial das fontes
```

Para rodar localmente: `pip install requests && python -m coletor.main`.

## Formato do enriquecimento

`dados/enriquecimento.json` guarda, por `id` do registro:

```json
{
  "atualizado_em": "2026-11-15",
  "itens": {
    "a_62268ea6e593": {
      "conferido_em": "2026-11-15",
      "link_edital": "https://...",
      "descricao": "Texto curto, escrito a partir do edital.",
      "cronograma": [
        {"evento": "Inscrições", "inicio": "2026-10-30", "fim": "2026-11-30"},
        {"evento": "Prova objetiva", "inicio": "2026-12-20"}
      ],
      "pcd": {
        "percentual": "5%", "vagas_reservadas": 2,
        "laudo": "…", "prazo_envio": "…", "forma_envio": "…", "observacoes": "…"
      },
      "correcoes": {"banca": "…", "link_primario": "https://..."}
    }
  }
}
```

O que estiver em `correcoes` substitui o campo correspondente do registro na página e o tira da lista "a conferir".

## Revisão semanal: registro de divergências

Ao conferir um registro no edital, a revisão semanal grava também, na entrada do registro em `dados/enriquecimento.json`, o campo `conferencia`: `{"campos_conferidos": ["inscricao_fim", "vagas", ...], "divergencias": [{"campo": "...", "base": "...", "edital": "..."}]}`. Entram em `campos_conferidos` só os campos que a base já trazia preenchidos e que foram comparados com o edital. Campo que a base trazia vazio e marcado "a conferir" não é divergência.

O e-mail semanal informa a taxa de acerto acumulada: campos conferidos sem divergência dividido pelo total de campos conferidos, somando todas as entradas de `enriquecimento.json`, e lista as divergências da semana.
