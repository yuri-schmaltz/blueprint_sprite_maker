# Checklist de Qualidade — My Blueprint Maker

> Derivado das diretrizes de **Obsessão pelo Objetivo** do `gabarito_ia.pdf`.
> Use esta checklist antes de cada commit ou PR significativo.

---

## Pré-Commit

### Correção
- [ ] O código faz o que o commit message promete?
- [ ] Todos os testes existentes passam? (`pytest tests/`)
- [ ] Novos caminhos de código têm testes associados?
- [ ] Edge cases foram considerados? (input vazio, None, valores extremos)

### Confiabilidade
- [ ] Exceções são tipadas e tratadas especificamente (não `except Exception` genérico)?
- [ ] Logging estruturado (`logging.getLogger(__name__)`) é usado em vez de `print()`?
- [ ] Recursos (arquivos, connections) são fechados/liberados corretamente?
- [ ] Operações em threads são thread-safe?

### Manutenibilidade
- [ ] Funções públicas têm docstring com Args, Returns e Raises?
- [ ] Variáveis e funções têm nomes que comunicam intenção?
- [ ] Magic numbers foram substituídos por constantes nomeadas?
- [ ] Comentários explicam o **porquê**, não o **o quê**?

### Performance
- [ ] Operações pesadas (IA, I/O) rodam em thread separada?
- [ ] Imagens grandes são processadas sem copiar desnecessariamente?
- [ ] Não há loops O(n²) desnecessários?

---

## Pré-Release

### Funcionalidade
- [ ] O modo standalone (Qt) abre e funciona sem erro?
- [ ] O plugin GIMP carrega sem erro no GIMP 3+?
- [ ] Processamento em lote completa sem travar?
- [ ] Preview 3D renderiza corretamente?

### Compatibilidade
- [ ] Testado em Linux e Windows?
- [ ] Funciona com Python 3.8+ (mínimo do projeto)?
- [ ] GIMP 3.0 e 3.2 suportados?

### Documentação
- [ ] README.md atualizado com mudanças relevantes?
- [ ] ARCHITECTURE.md reflete a realidade do código?
- [ ] CHANGELOG atualizado (se existir)?

---

## Sinais de Alerta (Red Flags)

> Se qualquer item abaixo for verdadeiro, **pare e reconsidere** antes de fazer commit:

- 🚩 "Funciona, mas não sei por quê"
- 🚩 "Precisa de um TODO para arrumar depois"
- 🚩 "Só falha em casos raros"
- 🚩 "Copiei de outra parte do código sem entender"
- 🚩 "O teste é frágil mas passa na maioria das vezes"

---

## Referências

- Diretrizes de desenvolvimento: [`.gemini/STYLE.md`](../.gemini/STYLE.md)
- Arquitetura: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)
- Princípios originais: [`docs/assets/gabarito_ia.pdf`](assets/gabarito_ia.pdf)
