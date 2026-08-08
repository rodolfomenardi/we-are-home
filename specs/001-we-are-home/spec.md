# Feature Specification: Simulador de Presença Inteligente

**Feature Branch**: `001-we-are-home`

**Created**: 2026-08-08

**Status**: Draft

**Input**: User description: "Desenvolver um simulador de presença inteligente para Home Assistant, distribuído via HACS. O diferencial é usar modelos probabilísticos leves (cadeias de Markov, inferência Bayesiana, distribuições condicionais) para aprender padrões reais de uso da casa a partir do histórico do recorder e gerar simulações sintéticas realistas."

## Clarifications

### Session 2026-08-08

- Q: Qual nível de complexidade de sequências o sistema deve aprender na v1? → A: Pares encadeáveis (B) — o sistema aprende associações temporais entre pares de entidades (A→B) e o simulador consegue encadear múltiplos pares durante a simulação (se A→B e B→C, pode gerar A→B→C).
- Q: Como o sistema deve modelar o intervalo de tempo entre eventos de uma sequência? → A: Distribuição do delay (B) — o sistema aprende média e desvio padrão do intervalo entre eventos do par, e o simulador sampleia da distribuição com ruído Gaussiano para gerar delays realistas.
- Q: Como balancear sequências aprendidas com perfis independentes durante a simulação? → A: Sequência como boost (B) — quando o evento A dispara, a probabilidade de B nas próximas janelas recebe um aumento temporário (multiplicador de probabilidade) proporcional ao delay aprendido, em vez de forçar deterministicamente o evento B.
- Q: Qual a janela máxima para considerar associação entre eventos consecutivos? → A: Configurável pelo usuário (D) com valor padrão de 60 minutos.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configurar Integração e Selecionar Dispositivos (Priority: P1)

O usuário instala a integração via HACS e, através da interface de configuração do Home Assistant, seleciona quais entidades (luzes, interruptores, persianas, climatização, media players, cenas) deseja que o sistema aprenda e controle durante a simulação. O usuário configura parâmetros básicos como intervalo de atualização do aprendizado e comportamento ao desligar a simulação.

**Why this priority**: Sem configuração inicial não há dados para aprender nem entidades para controlar. É o ponto de entrada obrigatório da integração.

**Independent Test**: Pode ser testado instalando a integração em qualquer instância do Home Assistant com recorder ativo, selecionando entidades e salvando a configuração — o sistema deve aparecer como uma integração configurada com switch de controle.

**Acceptance Scenarios**:

1. **Given** que o Home Assistant possui a integração instalada, **When** o usuário acessa "Dispositivos e Serviços" e adiciona a integração "We Are Home", **Then** uma interface de configuração é exibida permitindo selecionar entidades por domínio e configurar parâmetros iniciais.
2. **Given** que o usuário selecionou 5 entidades e salvou a configuração, **When** a configuração é concluída, **Then** um switch `switch.we_are_home` é criado e fica disponível no dashboard.
3. **Given** que a integração está configurada, **When** o usuário reabre as opções da integração, **Then** pode adicionar ou remover entidades da lista monitorada sem perder os dados já aprendidos.

---

### User Story 2 - Aprendizado Automático de Padrões (Priority: P1)

Após a configuração, o sistema consulta o histórico armazenado no recorder do Home Assistant e constrói perfis probabilísticos para cada entidade selecionada. Além dos perfis independentes por entidade, o sistema descobre automaticamente regras de associação temporal entre pares de entidades (sequências), aprendendo não apenas que "a luz acende às 19h" mas também que "quando a luz da sala acende, a TV costuma ligar 2 minutos depois". O aprendizado é contínuo: periodicamente, novos dados do recorder são incorporados aos perfis e regras de sequência existentes sem necessidade de re-treinamento completo. Os perfis capturam padrões por dia da semana e horário, diferenciando automaticamente dias úteis de fins de semana.

**Why this priority**: O aprendizado é o diferencial central do produto. Sem ele, a simulação não tem inteligência e o produto perde sua proposta de valor frente a alternativas existentes.

**Independent Test**: Configurar a integração com uma instância do Home Assistant que tenha pelo menos 7 dias de histórico real e verificar que após o período inicial de aprendizado, os perfis contêm probabilidades distintas para dias úteis versus fins de semana.

**Acceptance Scenarios**:

1. **Given** que a integração está configurada com entidades selecionadas e há pelo menos 7 dias de histórico no recorder, **When** o aprendizado inicial é concluído, **Then** cada entidade possui um perfil com probabilidades de estar ligada/desligada para cada janela de 15 minutos de cada dia da semana.
2. **Given** que o sistema está aprendendo há mais de 14 dias, **When** novos dados são incorporados, **Then** o sistema atualiza incrementalmente os perfis sem apagar o conhecimento anterior, dando mais peso a dados recentes.
3. **Given** que o usuário tem rotinas diferentes em dias úteis e fins de semana, **When** o aprendizado processa 4 semanas de dados, **Then** o sistema detecta automaticamente o agrupamento weekday/weekend e gera perfis distintos para cada grupo.
4. **Given** que uma entidade tem pouco histórico (menos de 3 dias), **When** o sistema tenta aprender seu padrão, **Then** o sistema indica baixa confiança no perfil e prioriza acumular mais observações antes de usá-lo na simulação.
5. **Given** que há pelo menos 14 dias de histórico com múltiplas entidades, **When** o aprendizado processa os dados, **Then** o sistema descobre automaticamente regras de associação temporal entre pares de entidades (ex: `light.sala ON` → `media_player.tv ON` com delay médio de 2 minutos) que ocorreram no mínimo 3 vezes.
6. **Given** que uma regra de sequência A→B foi aprendida, **When** novos dados são incorporados, **Then** a média e desvio padrão do delay entre A e B são atualizados incrementalmente.

---

### User Story 3 - Ativar e Desativar Simulação (Priority: P2)

O usuário ativa a simulação de presença através do switch da integração e o sistema começa a gerar comportamentos sintéticos baseados nos perfis aprendidos. Os dispositivos ligam e desligam em horários estatisticamente plausíveis, seguindo os padrões da casa mas sem repetir exatamente um dia específico do histórico. Ao desativar, o sistema restaura opcionalmente os estados anteriores dos dispositivos.

**Why this priority**: A simulação é o valor entregue ao usuário final. Depende do aprendizado (P1) mas é a funcionalidade que justifica toda a integração.

**Independent Test**: Com perfis já aprendidos, ativar o switch de simulação e observar que dentro de alguns minutos os dispositivos começam a receber comandos coerentes com os padrões históricos da casa.

**Acceptance Scenarios**:

1. **Given** que os perfis foram aprendidos e o switch está desligado, **When** o usuário liga o switch `switch.we_are_home`, **Then** a simulação inicia e começa a enviar comandos para as entidades configuradas seguindo as probabilidades dos perfis, com regras de sequência atuando como boost temporário de probabilidade (ex: se a luz da sala liga, a probabilidade da TV ligar aumenta temporariamente nas próximas janelas).
2. **Given** que a simulação está ativa há 2 horas, **When** o usuário desliga o switch, **Then** todos os dispositivos retornam opcionalmente ao estado que tinham antes da simulação começar.
3. **Given** que a simulação está ativa em uma terça-feira, **When** o sistema gera eventos para aquele dia, **Then** o comportamento segue o padrão estatístico de terças-feiras (dia útil), não de sábados ou domingos.
4. **Given** que a simulação está ativa há vários dias consecutivos, **When** o sistema completa um ciclo semanal, **Then** ele gera uma nova semana sintética com variações aleatórias dentro da distribuição aprendida, sem repetir exatamente a semana anterior.

---

### User Story 4 - Visualizar Perfis e Confiança (Priority: P3)

O usuário pode inspecionar os perfis aprendidos para cada entidade, verificar o nível de confiança do modelo e entender quais padrões foram detectados. Estas informações ficam disponíveis via diagnóstico do Home Assistant e via serviços.

**Why this priority**: Transparência e debug são importantes para confiança no sistema, mas o valor principal está no aprendizado e simulação automáticos (P1 e P2).

**Independent Test**: Chamar o serviço `get_profile` para uma entidade específica e receber um relatório contendo probabilidades por dia/horário e métrica de confiança.

**Acceptance Scenarios**:

1. **Given** que o sistema aprendeu perfis para `light.sala`, **When** o usuário chama o serviço `we_are_home.get_profile` com `entity_id=light.sala`, **Then** o sistema retorna as probabilidades P(on) agregadas por dia da semana e faixa horária, além da confiança média do perfil.
2. **Given** que uma entidade tem confiança abaixo de 60%, **When** o usuário acessa o diagnóstico da integração, **Then** o sistema indica que aquela entidade precisa de mais dados históricos para simulação confiável.

---

### User Story 5 - Integrar com Automações (Priority: P3)

Usuários avançados podem disparar a simulação via automações do Home Assistant usando os serviços expostos, permitindo cenários como ativar a simulação automaticamente quando todos saem de casa (via geofencing) ou em horários programados.

**Why this priority**: Integração com automações é uma funcionalidade de power-user que amplia o valor do sistema, mas não é essencial para o uso básico.

**Independent Test**: Criar uma automação no Home Assistant que chama `we_are_home.start` quando um dispositivo rastreador sai de casa e verificar que a simulação inicia automaticamente.

**Acceptance Scenarios**:

1. **Given** que o usuário tem uma automação configurada, **When** a automação chama o serviço `we_are_home.start`, **Then** a simulação inicia exatamente como se o switch tivesse sido ligado manualmente.
2. **Given** que a simulação está ativa, **When** uma automação chama `we_are_home.stop`, **Then** a simulação para e os estados são restaurados conforme configurado.

---

### Edge Cases

- O que acontece quando o recorder não tem histórico suficiente (menos de 24h de dados)?
- Como o sistema lida com entidades que ficaram offline ou indisponíveis durante o período de aprendizado?
- O que acontece se o usuário adicionar uma entidade nova (sem histórico) a uma simulação já em andamento?
- Como o sistema se comporta quando o Home Assistant é reiniciado durante a simulação?
- O que acontece se o banco do recorder for corrompido ou purgado durante o aprendizado?
- Como o sistema lida com entidades que mudam de estado muito frequentemente (ex: sensor de movimento)?
- O que acontece quando há feriados ou dias atípicos no histórico (ex: festa em casa)?
- Como o sistema lida com regras de sequência conflitantes (ex: A→B e A→C com delays sobrepostos)?
- O que acontece quando uma sequência parcial é interrompida (ex: A disparou o boost para B, mas B não ocorreu dentro da janela esperada)?
- Como o sistema trata entidades que participam de sequências mas são removidas da configuração? As regras que dependem delas são desativadas?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE permitir ao usuário selecionar quais entidades (de qualquer domínio suportado: light, switch, cover, media_player, climate, scene, input_boolean, fan, humidifier) serão monitoradas e controladas pela integração.
- **FR-002**: O sistema DEVE consultar o banco de dados do recorder do Home Assistant para extrair o histórico de estados das entidades selecionadas.
- **FR-003**: O sistema DEVE construir perfis probabilísticos para cada entidade que incluam: probabilidade de estar ligado para cada faixa de horário de cada dia da semana, probabilidade de mudar de estado, e duração típica quando ligado.
- **FR-004**: O sistema DEVE diferenciar automaticamente padrões de dias úteis (segunda a sexta) e fins de semana (sábado e domingo), com opção de agrupamento manual pelo usuário.
- **FR-005**: O sistema DEVE atualizar os perfis de forma incremental e contínua, incorporando novos dados do recorder sem necessidade de re-treinamento completo.
- **FR-006**: O sistema DEVE gerar simulações sintéticas que respeitem as distribuições de probabilidade aprendidas, com variação aleatória suficiente para que dois dias simulados nunca sejam idênticos.
- **FR-007**: O sistema DEVE expor um switch entity (`switch.we_are_home`) que inicia e para a simulação.
- **FR-008**: O sistema DEVE oferecer uma interface de configuração via UI (config flow) para seleção de entidades e parâmetros.
- **FR-009**: O sistema DEVE restaurar opcionalmente os estados anteriores dos dispositivos ao desligar a simulação.
- **FR-010**: O sistema DEVE funcionar inteiramente local, sem dependência de serviços em nuvem ou APIs externas.
- **FR-011**: O sistema DEVE expor serviços: `start` (iniciar simulação com parâmetros opcionais), `stop` (parar simulação), `train` (forçar re-treinamento), `get_profile` (retornar perfil aprendido de uma entidade), `list_rules` (listar regras de sequência descobertas).
- **FR-012**: O sistema DEVE consumir menos de 100 MB de RAM adicional e usar menos de 5% de CPU em hardware típico de Home Assistant (Raspberry Pi 4) durante operação normal.
- **FR-013**: O sistema DEVE registrar um nível de confiança para cada perfil, baseado na quantidade e qualidade dos dados históricos disponíveis.
- **FR-014**: O sistema DEVE ignorar entidades com confiança abaixo de um threshold configurável durante a simulação (não enviar comandos para entidades com padrão insuficientemente aprendido).
- **FR-015**: O sistema DEVE descobrir automaticamente regras de associação temporal entre pares de entidades (A→B) a partir do histórico, identificando pares que ocorrem com frequência mínima configurável (default: 3 ocorrências) e calculando média e desvio padrão do intervalo de tempo entre os eventos.
- **FR-016**: O sistema DEVE usar regras de sequência como boost temporário de probabilidade durante a simulação: quando o evento A ocorre, a probabilidade base de B nas próximas janelas de tempo é multiplicada por um fator de boost que decai com o tempo, em vez de forçar deterministicamente o evento B.
- **FR-017**: O sistema DEVE permitir ao usuário configurar a janela máxima de tempo (em minutos) usada para descobrir associações entre eventos, com valor padrão de 60 minutos.
- **FR-018**: O sistema DEVE permitir que o simulador encadeie múltiplos pares de sequência durante a simulação, de modo que se existem regras A→B e B→C, o sistema possa gerar a cadeia A→B→C respeitando os delays aprendidos.

### Key Entities

- **TimeProfile**: Representa o perfil probabilístico de uma entidade. Contém probabilidades P(on) e P(transição) para cada faixa de horário em cada dia da semana, além da duração média dos eventos. Os perfis são agrupados automaticamente por tipo de dia (dia útil vs fim de semana).
- **SequenceRule**: Representa uma regra de associação temporal entre duas entidades (A→B). Contém as entidades origem e destino, o estado que dispara a regra, a média e desvio padrão do delay entre A e B, a frequência de ocorrência observada, e o fator de boost a ser aplicado na simulação.
- **EntityConfig**: Configuração de uma entidade monitorada. Inclui entity_id, domínio, se está ativa para simulação, threshold de confiança mínimo, e data da última atualização do perfil.
- **SimulationState**: Estado atual da simulação. Inclui switch_id, lista de entidades sendo simuladas, timestamp de início, estado pré-simulação de cada entidade (para restauração), e boosts temporários ativos decorrentes de sequências disparadas.
- **LearningRun**: Registro de uma execução de aprendizado. Inclui timestamp, entidades processadas, número de novas observações incorporadas, regras de sequência descobertas, e métricas de confiança resultantes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Um usuário com instalação padrão do Home Assistant (recorder com 10 dias de histórico) consegue configurar a integração e ter perfis funcionais em menos de 10 minutos após a instalação.
- **SC-002**: A simulação gera comportamentos que são indistinguíveis de um dia real para um observador externo em pelo menos 80% dos casos, medido por teste cego de vizinhos ou familiares.
- **SC-003**: O sistema mantém performance estável (sem aumento progressivo de consumo de RAM ou CPU) durante 30 dias consecutivos de simulação contínua.
- **SC-004**: Usuários conseguem ativar e desativar a simulação com um único toque no dashboard do Home Assistant, sem necessidade de documentação adicional.
- **SC-005**: A atualização incremental de perfis processa novos dados em menos de 30 segundos para até 50 entidades monitoradas em um Raspberry Pi 4.
- **SC-006**: O sistema diferencia corretamente padrões weekday/weekend em 90% dos lares após 4 semanas de dados, validado por inspeção manual dos perfis.
- **SC-007**: 95% dos comandos gerados pela simulação resultam em mudança efetiva de estado do dispositivo (sem comandos redundantes para dispositivos que já estão no estado alvo).
- **SC-008**: O sistema descobre pelo menos 80% das associações temporais reais entre entidades que um humano identificaria nos mesmos dados históricos, após 14 dias de treinamento.

## Assumptions

- O usuário possui o recorder do Home Assistant ativo com pelo menos 7 dias de histórico para um aprendizado inicial significativo.
- O Home Assistant está rodando em hardware compatível (Raspberry Pi 4 ou superior) com Python 3.12+.
- A integração `history` está habilitada (padrão do Home Assistant).
- O usuário tem permissão para instalar integrações customizadas via HACS.
- Os dispositivos controlados respondem aos comandos padrão `homeassistant.turn_on` / `homeassistant.turn_off`.
- Feriados e eventos atípicos são tratados como outliers que o sistema pode opcionalmente detectar e filtrar, mas não é requisito da v1.
- O sistema usa exclusivamente bibliotecas já disponíveis no Home Assistant (numpy) ou inclusas na stdlib do Python, sem dependências externas adicionais.
- A simulação não envia comandos para entidades que estão sendo operadas manualmente durante a simulação (conflito resolvido por último comando prevalece).
- A descoberta de sequências requer um mínimo de 3 ocorrências do mesmo par A→B para ser considerada uma regra válida; este threshold é configurável.
- A janela de tempo para considerar dois eventos como parte de uma sequência é configurável com valor padrão de 60 minutos.
