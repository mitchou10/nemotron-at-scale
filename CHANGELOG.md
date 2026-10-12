# Changelog

## [0.5.1](https://github.com/mitchou10/nemotron-at-scale/compare/v0.5.0...v0.5.1) (2026-10-12)


### Bug Fixes

* **tts:** chmod the voices in a RUN, Kaniko cannot parse a symbolic COPY --chmod ([bc1eeda](https://github.com/mitchou10/nemotron-at-scale/commit/bc1eeda72ff05858ecc72a541abcd0e633e28245))

## [0.5.1-rc](https://github.com/mitchou10/nemotron-at-scale/compare/v0.5.0...v0.5.1-rc) (2026-10-12)


### Bug Fixes

* **tts:** chmod the voices in a RUN, Kaniko cannot parse a symbolic COPY --chmod ([6801e04](https://github.com/mitchou10/nemotron-at-scale/commit/6801e04a4af0b7b9a55db9749ff36bd89d1beea7))

## [0.5.0](https://github.com/mitchou10/nemotron-at-scale/compare/v0.4.0...v0.5.0) (2026-10-12)


### Features

* **helm:** run the alembic migration as a hook job in the dev environment ([4bd7e33](https://github.com/mitchou10/nemotron-at-scale/commit/4bd7e337aecb6f422e7d919346f922ad7114fd2b))


### Code Refactoring

* **helm:** split the DSO values into a common base and a minimal dev file ([b047f6d](https://github.com/mitchou10/nemotron-at-scale/commit/b047f6db7e7d46d46077c8f4e744c0c0320831ae))

## [0.4.0](https://github.com/mitchou10/nemotron-at-scale/compare/v0.3.0...v0.4.0) (2026-10-12)


### Features

* **backend:** admin statistics API and TTS call log ([42af207](https://github.com/mitchou10/nemotron-at-scale/commit/42af2075c5282229683ad9f3616d688cd8aa0410))
* **backend:** instance registry, gateway for STT and TTS ([7a58c5f](https://github.com/mitchou10/nemotron-at-scale/commit/7a58c5f90076ed1f46d5ef974550236442644c20))
* **deploy:** wire the registry in compose and the chart, update the docs ([56ffb4d](https://github.com/mitchou10/nemotron-at-scale/commit/56ffb4d79ca29bfdd4d12bc36ff2a1164943a001))
* **frontend:** admin interface with React, Tailwind CSS and shadcn/ui ([22e28a1](https://github.com/mitchou10/nemotron-at-scale/commit/22e28a12cd3292ad641e158d607fafd53c643a1a))
* **helm:** add CloudNativePG cluster and Vault secrets for dev ([0a3627d](https://github.com/mitchou10/nemotron-at-scale/commit/0a3627d48e073763db31e83dadd9a3d76418b534))
* **helm:** add common-values.yaml to try the chart as is ([5c7070f](https://github.com/mitchou10/nemotron-at-scale/commit/5c7070fa5b08b3d393df5ca6143f661719793e6d))
* **helm:** add global ingress and the dev environment values ([cba762e](https://github.com/mitchou10/nemotron-at-scale/commit/cba762edabc553e55d2377babdc15b9d05c76e4b))
* **vosk,tts:** register in the backend registry with a heartbeat ([bd38ccb](https://github.com/mitchou10/nemotron-at-scale/commit/bd38ccbed4161822d0ab96e0c2140b94abbe119b))


### Bug Fixes

* **frontend:** track src/lib, which the Python .gitignore rule hid ([861ce0f](https://github.com/mitchou10/nemotron-at-scale/commit/861ce0f652e2d02eab8023854cf82d44cafbf023))
* **tts:** make the voice files readable by any uid ([2c9b930](https://github.com/mitchou10/nemotron-at-scale/commit/2c9b9303c3800b946081361e9274b5c755003ed5))

## [0.2.0-rc.3](https://github.com/mitchou10/nemotron-at-scale/compare/v0.2.0-rc.2...v0.2.0-rc.3) (2026-10-11)


### Bug Fixes

* **tts:** make the voice files readable by any uid ([0930c52](https://github.com/mitchou10/nemotron-at-scale/commit/0930c5296bc63ff7010d60cab15d8614abbe9671))

## [0.2.0-rc.2](https://github.com/mitchou10/nemotron-at-scale/compare/v0.2.0-rc.1...v0.2.0-rc.2) (2026-10-11)


### Features

* **backend:** admin statistics API and TTS call log ([613efa2](https://github.com/mitchou10/nemotron-at-scale/commit/613efa215530d4e247e240c181de179f969ebf8d))
* **backend:** instance registry, gateway for STT and TTS ([bb5b8cd](https://github.com/mitchou10/nemotron-at-scale/commit/bb5b8cd816cc4a44a4117c17c6c04c441ac89df4))
* **deploy:** wire the registry in compose and the chart, update the docs ([a40258d](https://github.com/mitchou10/nemotron-at-scale/commit/a40258d8c3a60a5e23fc2233eaf7f10ddcbe8ae5))
* **frontend:** admin interface with React, Tailwind CSS and shadcn/ui ([560d52f](https://github.com/mitchou10/nemotron-at-scale/commit/560d52f60b1fbc6c285ebd767542d864035b409c))
* **helm:** add CloudNativePG cluster and Vault secrets for dev ([b3c4cd5](https://github.com/mitchou10/nemotron-at-scale/commit/b3c4cd516c842af3c514ce9965a1bd2dfd937072))
* **vosk,tts:** register in the backend registry with a heartbeat ([b7026a6](https://github.com/mitchou10/nemotron-at-scale/commit/b7026a6df51e88df9b2e14d4d70b19283584ae7d))


### Bug Fixes

* **frontend:** track src/lib, which the Python .gitignore rule hid ([6f27f4e](https://github.com/mitchou10/nemotron-at-scale/commit/6f27f4e0e7e4b773af0839d10d1d6fe9b5ae178a))

## [0.2.0-rc.1](https://github.com/mitchou10/nemotron-at-scale/compare/v0.2.0-rc...v0.2.0-rc.1) (2026-10-02)


### Features

* **backend:** relay /api/v1/audio/speech to the TTS service ([213a086](https://github.com/mitchou10/nemotron-at-scale/commit/213a086be8fc7bbc0bd4790dbe0511173c032446))
* **frontend:** serve the status page from its own nginx service ([8f226b7](https://github.com/mitchou10/nemotron-at-scale/commit/8f226b75e77c066044283f610bac9d2f1f1ce2da))
* **helm:** add chart for backend and vosk services ([541ce89](https://github.com/mitchou10/nemotron-at-scale/commit/541ce8984d44f26041921f17cc60024443db40f9))
* **helm:** add common-values.yaml to try the chart as is ([9f230d0](https://github.com/mitchou10/nemotron-at-scale/commit/9f230d0cfd4e3dfee06150c0bc77af4144ad4d2a))
* **helm:** add frontend component ([33971ca](https://github.com/mitchou10/nemotron-at-scale/commit/33971cabd92cf283bb37a8eb2178be224ec88cba))
* **helm:** add global ingress and the dev environment values ([790bce9](https://github.com/mitchou10/nemotron-at-scale/commit/790bce9a1d337cca5089de656febb74b00df1f68))
* **helm:** add tts component and wire the backend to it ([0d0c3b9](https://github.com/mitchou10/nemotron-at-scale/commit/0d0c3b9debedebaeea2a062bb01af9351ae1329d))
* **status:** add ASR workers status page with history ([b13a9c2](https://github.com/mitchou10/nemotron-at-scale/commit/b13a9c2dbdb6cd2f46c6c78b6dfe561dcd6306f0))
* **tts:** add OpenAI-compatible text-to-speech service (Piper) ([a1fae10](https://github.com/mitchou10/nemotron-at-scale/commit/a1fae1053eda1f18eccabfd4ed9c90677358000c))
* **tts:** ship the default voice inside the image ([636be95](https://github.com/mitchou10/nemotron-at-scale/commit/636be954be282b91fb724d99695b90faa5aa7ff7))

## [0.3.0](https://github.com/mitchou10/nemotron-at-scale/compare/v0.2.0...v0.3.0) (2026-10-02)


### Features

* **backend:** relay /api/v1/audio/speech to the TTS service ([213a086](https://github.com/mitchou10/nemotron-at-scale/commit/213a086be8fc7bbc0bd4790dbe0511173c032446))
* **frontend:** serve the status page from its own nginx service ([8f226b7](https://github.com/mitchou10/nemotron-at-scale/commit/8f226b75e77c066044283f610bac9d2f1f1ce2da))
* **helm:** add frontend component ([33971ca](https://github.com/mitchou10/nemotron-at-scale/commit/33971cabd92cf283bb37a8eb2178be224ec88cba))
* **helm:** add tts component and wire the backend to it ([0d0c3b9](https://github.com/mitchou10/nemotron-at-scale/commit/0d0c3b9debedebaeea2a062bb01af9351ae1329d))
* **tts:** add OpenAI-compatible text-to-speech service (Piper) ([a1fae10](https://github.com/mitchou10/nemotron-at-scale/commit/a1fae1053eda1f18eccabfd4ed9c90677358000c))
* **tts:** ship the default voice inside the image ([636be95](https://github.com/mitchou10/nemotron-at-scale/commit/636be954be282b91fb724d99695b90faa5aa7ff7))

## [0.2.0-rc](https://github.com/mitchou10/nemotron-at-scale/compare/v0.1.0...v0.2.0-rc) (2026-10-02)


### Features

* **backend:** relay /api/v1/audio/speech to the TTS service ([08c815f](https://github.com/mitchou10/nemotron-at-scale/commit/08c815f754d659494090eb6e4f02e2fc73ef269a))
* **frontend:** serve the status page from its own nginx service ([a380d15](https://github.com/mitchou10/nemotron-at-scale/commit/a380d155a7339509f728a8775c5d548e784801c9))
* **helm:** add chart for backend and vosk services ([541ce89](https://github.com/mitchou10/nemotron-at-scale/commit/541ce8984d44f26041921f17cc60024443db40f9))
* **helm:** add frontend component ([e215680](https://github.com/mitchou10/nemotron-at-scale/commit/e215680ca8163b715a6ff4d3c19e5981a6fa0ac0))
* **helm:** add tts component and wire the backend to it ([20b17a9](https://github.com/mitchou10/nemotron-at-scale/commit/20b17a957315279d0e3f777e91854564aaf6838f))
* **status:** add ASR workers status page with history ([b13a9c2](https://github.com/mitchou10/nemotron-at-scale/commit/b13a9c2dbdb6cd2f46c6c78b6dfe561dcd6306f0))
* **tts:** add OpenAI-compatible text-to-speech service (Piper) ([3de5db0](https://github.com/mitchou10/nemotron-at-scale/commit/3de5db04bd74b2ac4cce18c879c273df43eecc5f))
* **tts:** ship the default voice inside the image ([8f1aa17](https://github.com/mitchou10/nemotron-at-scale/commit/8f1aa178baf156fca42a719db13d90da8b2a3aef))

## [0.2.0](https://github.com/mitchou10/nemotron-at-scale/compare/v0.1.0...v0.2.0) (2026-10-02)


### Features

* **helm:** add chart for backend and vosk services ([541ce89](https://github.com/mitchou10/nemotron-at-scale/commit/541ce8984d44f26041921f17cc60024443db40f9))
* **status:** add ASR workers status page with history ([b13a9c2](https://github.com/mitchou10/nemotron-at-scale/commit/b13a9c2dbdb6cd2f46c6c78b6dfe561dcd6306f0))
