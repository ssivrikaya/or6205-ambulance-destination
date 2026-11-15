# Model formülasyonu: protokol içi çok amaçlı ambulans–hastane atama modeli

Bu belge `formulation.py`, `model_gurobi.py` ve `model_highs.py` dosyalarındaki modelin birebir matematiksel karşılığıdır. Kısıt numaraları koddaki yorum satırlarıyla aynıdır.

## 1. Kümeler

| Sembol | Anlamı |
|---|---|
| $I$ | Günün ambulans taşımaları (hastalar) |
| $J$ | Hastaneler ve uydu acil birimleri (SEF) |
| $A \subseteq I \times J$ | Protokolün izin verdiği (hasta, hastane) çiftleri; `protocol.py` üretir |
| $A_i = \{j : (i,j) \in A\}$ | Hasta $i$ için izinli hastaneler |
| $T = \{t_0, \dots, t_1 + D\}$ | 15 dakikalık periyotlar; $D = 16$ drenaj periyodu, son varıştan sonra kuyrukların boşalması için eklenir |
| $H$ | Günün saatleri (0–25) |
| $K$ | Kalabalık maliyeti segmentleri ($k = 0, \dots, 3$) |
| $I_A, I_B \subseteq I$ | Genel sınıftaki hastaların demografik grupları (eşitlik kısıtı için) |

## 2. Parametreler

| Sembol | Anlamı | Kaynak |
|---|---|---|
| $T_{ij}$ | 911 çağrısından kesin tedaviye geçen süre (dk), kuyruk beklemesi hariç. Hastane $j$ kesin tedaviyi veremiyorsa ikincil sevk süresi dahildir. | `protocol.py` → `T_no_wait` |
| $w_i$ | Aciliyet ağırlığı | `config.ACUITY_WEIGHT` |
| $\pi$ | Tedavi sürekliliğine uymanın değeri (eşdeğer dakika) | `MODEL["continuity_value"]` |
| $\hat c_i$, $\kappa_i$ | Hastanın süreklilik hastanesi; $\kappa_i = 1$ ise bu hastane $A_i$ içindedir | `instance.py`, `protocol.py` |
| $c_{ij}$ | $w_i T_{ij} + w_i \pi \kappa_i \mathbb{1}[j \neq \hat c_i]$ | `formulation.py` |
| $p_{ij}$, $h_{ij}$ | Hastane $j$'ye varış periyodu ve saati | `protocol.py` |
| $\mu_{jt}$ | Periyot $t$'de hastane $j$'nin ambulanstan devralabileceği hasta sayısı (boşaltma kapasitesi) | `evaluate.offload_rate` |
| $W_{jh}$ | Saat $h$'de beklenen ayakta başvuru sayısı | `hospitals.py` |
| $\mathrm{Cap}_j$ | Saatlik acil kapasitesi | `hospitals.py` |
| $\beta_k$, $s_k$ | Kullanım oranı kırılma noktaları $(0, 0.85, 1.0, 1.2)$ ve eğimler $(0, 1, 3, 10)$; eğimler artan olduğu için maliyet konvekstir | `config.CROWDING_*` |
| $u_{jk}$ | Segment genişliği: $(\beta_{k+1} - \beta_k)\,\mathrm{Cap}_j$; son segment sınırsız | `formulation.py` |
| $\lambda$ | Bir dakikalık kapı beklemesinin ağırlığı; varsayılan olarak hastaların ortalama aciliyet ağırlığı | `MODEL["wall_weight"]` |
| $\Delta$ | Periyot uzunluğu (15 dk) | `SIM["period_min"]` |
| $\theta$ | İkincil amacın ağırlığı (eşitlik bozucu, $10^{-4}$) | `MODEL["tie_break"]` |
| $\varepsilon$, $\delta$ | Pareto üst sınırı; eşitlik toleransı (isteğe bağlı) | çalışma anında |

## 3. Karar değişkenleri

$$x_{ij} \in \{0,1\} \quad (i,j) \in A \qquad \text{hasta } i \text{ hastane } j\text{'ye götürülür}$$

$$B_{jt} \ge 0 \qquad \text{periyot } t \text{ sonunda hastane } j\text{'de boşaltma bekleyen ambulans sayısı}$$

$$0 \le y_{jhk} \le u_{jk} \qquad \text{saat } h\text{'deki acil yükünün maliyet segmenti } k\text{'ya düşen kısmı}$$

## 4. Amaç fonksiyonları

**f1 — ambulans hizmeti ve hasta amacı.** Aciliyetle ağırlıklandırılmış kesin tedaviye ulaşma süresi, süreklilik cezası ve kapı beklemesinin toplamı:

$$f_1 = \sum_{(i,j)\in A} c_{ij}\, x_{ij} \;+\; \lambda \Delta \sum_{j\in J}\sum_{t\in T} B_{jt}$$

**f2 — hastane amacı.** Saatlik acil yükünün konveks, parçalı doğrusal kalabalık maliyeti:

$$f_2 = \sum_{j\in J}\sum_{h\in H}\sum_{k\in K} s_k\, y_{jhk}$$

## 5. Model $(P_\varepsilon)$

$$\min \; f_1 + \theta f_2$$

İkinci model $\min f_2 + \theta f_1$ olarak kurulur ve Pareto aralığının alt ucunu bulmak için kullanılır.

Kısıtlar:

$$\text{(1) Atama:} \quad \sum_{j \in A_i} x_{ij} = 1 \qquad \forall i \in I$$

$$\text{(2) Boşaltma kuyruğu:} \quad \sum_{i:\,(i,j)\in A,\; p_{ij}=t} x_{ij} \;+\; B_{j,t-1} \;-\; B_{jt} \;\le\; \mu_{jt} \qquad \forall j\in J,\; t\in T, \quad B_{j,t_0-1}=0$$

$$\text{(3) Saatlik yük:} \quad \sum_{k\in K} y_{jhk} \;=\; W_{jh} + \sum_{i:\,(i,j)\in A,\; h_{ij}=h} x_{ij} \qquad \forall j\in J,\; h\in H$$

$$\text{(4) Segment sınırları:} \quad 0 \le y_{jhk} \le u_{jk} \qquad \forall j, h, k$$

$$\text{(5) } \varepsilon\text{-kısıtı (Pareto):} \quad f_2 \le \varepsilon$$

$$\text{(6) Eşitlik (isteğe bağlı):} \quad -\delta \;\le\; \frac{1}{|I_B|}\sum_{i\in I_B}\sum_{j\in A_i} T_{ij}x_{ij} \;-\; \frac{1}{|I_A|}\sum_{i\in I_A}\sum_{j\in A_i} T_{ij}x_{ij} \;\le\; \delta$$

$$\text{(7) Kesinleşmiş kararlar (kayan ufuk):} \quad x_{ij} = 1 \qquad \forall (i,j) \in \mathcal{F}$$

$$\text{(8) Değişken tipleri:} \quad x_{ij}\in\{0,1\}, \quad B_{jt}\ge 0$$

Protokolün kendisi (POE planları, 10 ve 20 dakika bantları, code black, ambulans yoğunluğu koşulu) $A$ kümesinin içine gömülüdür. Modelde ayrıca bir protokol kısıtı yoktur: izinli olmayan bir yay için değişken hiç tanımlanmaz.

## 6. Doğrusallaştırmalar neden kesin?

**Kısıt (2), Lindley özyinelemesi.** $x$ sabitken (2) ve $B \ge 0$ koşullarını sağlayan en küçük $B$ değeri şudur:

$$B_{jt} = \max\{0,\; B_{j,t-1} + a_{jt} - \mu_{jt}\}$$

Bu tümevarımla gösterilebilir. Amaçta $B$'nin katsayısı $\lambda\Delta > 0$ olduğu için optimumda bu değer alınır. Böylece $\Delta \sum_t B_{jt}$, hastane $j$'deki toplam ambulans bekleme dakikasının akışkan (fluid) yaklaşımı olur. Ek bir ikili değişkene gerek yoktur.

**Kısıtlar (3)–(4), konveks parçalı maliyet.** Eğimler artan olduğu için her uygun $y$ için şu eşitsizlik geçerlidir:

$$\sum_k s_k y_{jhk} \ge \varphi_j(\text{yük})$$

Eşitlik, segmentler sırayla doldurulduğunda sağlanır. Dolayısıyla minimizasyonda $f_2$ gerçek kalabalık maliyetine eşittir. Aynı sebeple (5) numaralı kısıt da kesindir: sağlayan bir $y$ bulunması, $\varphi \le \varepsilon$ olmasıyla eşdeğerdir. Bu yüzden ek ikili değişken gerekmez.

**Doğrulama** (`verify_model.py`). İki test yapılır:
- **Kaba kuvvet karşılaştırması.** Altı küçük ve yoğun alt örnekte (her birinde 2.352–3.584 olası atama) tüm atamalar sayılır. Her biri, çözücüden bağımsız bir hesapla puanlanır: Lindley özyinelemesi ve kapalı formdaki konveks maliyet. Bu hesap f1, f2 ve bağlayıcı ε modlarında çözücünün optimumuyla karşılaştırılır. 18 testin 18'i geçti.
- **Amaç değerinin yeniden hesaplanması.** Tam günlerde çözücünün raporladığı amaç değeri, seçtiği atama için bağımsız olarak yeniden hesaplanır. İki değer aynı çıkmalıdır.

## 7. Boyut ve süre (sentetik gün, ~430 hasta)

| Bileşen | Değer |
|---|---|
| İkili değişken | ~800–850 |
| Toplam değişken | ~3.900 |
| Kısıt | ~2.250 |
| Tam gün çözüm süresi (HiGHS) | 0,1–0,2 s |
| Kayan ufuk, bir gün | ~100 çözüm, ~7 s |

Gurobi'nin daha da hızlı olması beklenir.

## 8. Gölge fiyatlar (E5)

$x$ optimum değerinde sabitlenir ve kalan doğrusal programın (LP) dual değerleri okunur. Kısıt (2)'nin duali şu anlama gelir:

$$-\frac{\partial z}{\partial \mu_{jt}}$$

Yani hastane $j$'de periyot $t$'de **bir hasta daha boşaltabilmenin** amaç fonksiyonu birimi (ağırlıklı dakika) cinsinden değeri. Gurobi'de bu `m.fixed()` ve `.Pi` ile, HiGHS'te `linprog` marjinalleriyle hesaplanır.

## 9. Varsayımlar ve sınırlılıklar

Bunları makalenin "Limitations" bölümüne yaz:

1. **Deterministik model.** Tam bilgi modu günü önceden bilir; kayan ufuk modu yalnızca o ana kadar gelen çağrıları bilir ve talep tahmini kullanmaz.
2. **Kuyruk yaklaşımı.** Model akışkan (fluid) kuyruk kullanır. Bütün politikalar ise aynı FIFO simülasyonuyla (`evaluate.py`) yeniden puanlanır.
3. **Kapsam.** Yalnızca varış hastanesi kararı modellenir; ambulans sevki (dispatch) ve dönüş yolculuğu modelin dışındadır.
4. **Varsayımsal parametreler.** $\pi$, $\lambda$, aciliyet ağırlıkları ve kalabalık eğimleri birer değerlendirme parametresidir. Duyarlılık analizi yapılmalı ve gerekçeleri yazılmalıdır.
5. **Protokol yorumları.** Plan metinlerindeki belirsiz noktalar için yapılan yorumlar README'de listelenmiştir.
