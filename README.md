# ROBCO Operations Terminal

Dashboard local de telemetria para usar em um iPad antigo. O computador executa o servidor; o iPad acessa a interface pelo navegador.

## Executar

Requer Python 3.10+.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.\\.venv\\Scripts\\python.exe app.py
```

Abra no computador:

```text
http://localhost:8080
```

No iPad, use o IP do computador na mesma rede:

```text
http://IP_DO_COMPUTADOR:8080
```

## O que aparece

A tela contém seis cards:

- Weather: cidade, clima, métricas e foto turística.
- System: CPU, memória e disco.
- Now Playing: mídia atual.
- Codex e Claude: status, modelo, tokens e limites.
- Pomodoro: foco e pausas.

O layout ocupa a tela inteira e foi ajustado para Safari/WebKit antigo. Não há barra superior nem abas.

## Localização e clima

O sistema tenta usar a localização do dispositivo. Se não houver GPS, usa uma estimativa por IP. O servidor consulta o clima e busca uma foto da cidade.

## Segurança

O servidor não possui autenticação e fica acessível na rede local. Não exponha a porta 8080 à internet.

O dashboard pode mostrar nome do computador, IDs de sessão, consumo dos agentes, mídia atual e localização aproximada. Senhas, chaves, prompts e respostas não são enviados pela API.

## Testes

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
```

Com o servidor rodando e Playwright instalado:

```powershell
.\\.venv\\Scripts\\python.exe tests/check_city_photo.py
```
