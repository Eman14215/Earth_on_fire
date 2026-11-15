# EARTH ON FIRE 🔥 — تطبيق رصد حرائق أفريقيا

نسخة قابلة للتشغيل على جهازك من مشروع EARTH ON FIRE، مبنية على ملفات الفريق الأصلية وبيانات NASA FIRMS بعد التنظيف. لا تحتوي على Chatbot، أو بيانات حرائق وهمية، أو تنبؤات خطورة غير معتمدة.

## ابدأ في 3 خطوات (Windows)

1. فك الضغط عن الملف `EARTH_ON_FIRE_COMPLETE.zip` في أي مجلد على جهازك، مثل Desktop.
2. تأكد إن **Python 3.10 أو أحدث** موجود على الجهاز ويعمل بالأمر `python --version` (وفعّل خيار Add Python to PATH أثناء التثبيت). يلزم اتصال إنترنت أول مرة لتثبيت المكتبات.
3. اضغط مرتين على **`start_windows.bat`**. بعدها افتح **http://127.0.0.1:8000** من المتصفح. سيظل السيرفر يعمل طالما نافذة Python مفتوحة.

لو على Mac أو Linux:

```bash
cd EARTH_ON_FIRE
bash start_linux_mac.sh
```

الرابط المحلي نفسه `http://127.0.0.1:8000`.

### بدون الإنترنت

البيانات كاملة بالفعل داخل الحزمة، والـBackend يعمل محليًا. يفضل وجود الإنترنت لتنزيل المكتبات مرة واحدة، وعرض طبقة OpenStreetMap وLeaflet/ECharts بشكلها الكامل. لو تعذر تحميلها، فيه خرائط ورسوم SVG احتياطية تعرض **البيانات الحقيقية** من نفس الـAPI. لإيقاف فحص GitHub التلقائي على جهاز غير متصل:

Windows في نافذة CMD:

```bat
set AUTO_SYNC=0
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

## الميزات المنفذة

- واجهة جديدة مستوحاة من تصميم `earth_on_fire_mvp_v2.html`، بقائمة صفحـات للأفراد والشركات.
- واجهة كاملة عربي/إنجليزي واتجاه RTL/LTR وتبديل فوري، من غير نسخ منفصلة للموقع.
- فلترة متسلسلة: **الإقليم الأفريقي ثم الدولة**. بعدها التاريخ، MODIS/VIIRS، الثقة، النهار/الليل.
- خريطة حرارية وكثافة رصد حقيقية بخلايا `0.25°` وأزرار لعرض نقاط الخلايا.
- تحليلات: إجمالي مرات الرصد، عدد الدول، أعلى FRP، المنحنى اليومي، مصادر الرصد، حسب الإقليم، حسب الدولة، حسب الساعة، وحسب الثقة.
- Time-lapse للأيام الموجودة في ملف المصدر.
- تسجيل حساب فرد أو شركة بكلمة مرور مخزنة بشكل salted PBKDF2، والجلسات محفوظة على الخادم في كوكي HttpOnly.
- مناطق متابعة قابلة للحفظ والحذف، مع موقع وإحداثيات ونصف قطر، وحساب واقعي لمرات الرصد القريبة وأعلى FRP داخل المسافة. تظهر مناطق التوريد في لوحة الشركة.
- تصدير CSV **ملخص يومي** ملتزم بفلاتر العرض.
- صفحة `More details` بدلًا من `NASA Challenge`، تشرح المصدر وحدود الدقة.
- الـAPI توثيق تلقائي: `http://127.0.0.1:8000/api/docs`.
- تحديث قراءة ملف GitHub الموجود عند الفريق كل 6 ساعات **طالما سيرفر التطبيق شغال وعنده اتصال بالإنترنت**.

## طبقة البيانات — أرقام نسخة الملف المرفوعة

| المقياس | القيمة |
|---|---:|
| إجمالي الصفوف في `africa_fires_cleaned.csv` | 489,891 |
| سجلات تقع ضمن حدود الدول الأفريقية الممثلة في ملف Natural Earth | 468,459 |
| سجلات لا تقع ضمن تلك الحدود (بما في ذلك خارج القارة وجزر/حدود غير ممثلة) | 21,432 |
| تاريخ بيانات المصدر | 6 إلى 15 نوفمبر 2026 |
| عدد الدول ذات عمليات رصد في النسخة | 48 |

ملف CSV الأصلي محفوظ **كما هو**. لم نغيّر عملية التنظيف الموجودة في GitHub. أضفنا فقط ربطًا جغرافيًا مشتقًا حسب حدود الدول الموجودة في `data/africa_countries.geojson`، مع حفظ تصنيف `Africa_Region` الأصلي للمراجعة.

**مهم:** عدد السجلات **مرات رصد فضائي** وليس عدد حرائق غابات فريدة. قد ترصد عدة أقمار نفس المصدر الحراري مرات متعددة. `FRP` قدرة إشعاعية بالنظام الميجاوات وليست احتمال الحريق أو درجة خطورة موثقة. تسميات شدة FRP موروثة من ملف الفريق وهي حدود مخصصة وليست معيار NASA رسميًا. مستشعرات MODIS وVIIRS تختلف في الدقة، وتوحيد `Confidence_Level` في الملف ليس معايرة إحصائية بين المستشعرين.

## التحديث الأوتوماتيكي

الرابط المصدر الذي يستخدمه المشروع:

`https://raw.githubusercontent.com/Eman14215/africa_fires_data/main/africa_fires_cleaned.csv`

- GitHub Actions الخاصة بالفريق تستمر في تجديد ملف المصدر طبقًا للجدول عندكم.
- السيرفر يراجع أحدث Commit للملف دوريًا عبر GitHub API. **إذا كان Commit أحدث** ينزّل CSV ويعيد بناء قاعدة بيانات جديدة ويبدّلها بشكل ذري (atomic swap)، فلا يتوقف الموقع بسبب إعادة بناء البيانات.
- في حالة انقطاع الإنترنت أو فشل تحديث المصدر، يستمر التطبيق بعرض آخر قاعدة بيانات صالحة محفوظة لديه.
- الواجهة تتحقق من تحديث البيانات كل 10 دقائق أثناء فتح الصفحة، وتعيد تحميلها عند وجود نسخة أحدث.
- `AUTO_SYNC=1` افتراضيًا؛ لتغييره استخدم متغير البيئة `AUTO_SYNC=0`. يمكن تغيير المدة `SYNC_INTERVAL_SECONDS=21600` (6 ساعات).
- للتحديث اليدوي (إن لزم): `python -m scripts.sync_github`.

## هيكل المشروع

```text
EARTH_ON_FIRE/
├─ app.py                        Backend FastAPI + Auth + filters + reports
├─ static/
│  ├─ index.html                 HTML app
│  ├─ app.css                    Responsive styling
│  └─ app.js                     Bilingual UI, charts, maps, authentication
├─ data/
│  ├─ africa_fires_cleaned.csv   Original cleaned data (unchanged)
│  ├─ africa_countries.geojson   Natural Earth low-resolution African polygons
│  └─ fires.sqlite              Prebuilt searchable dataset
├─ scripts/
│  ├─ build_db.py                Import + point-in-polygon + tile aggregation
│  └─ sync_github.py             Atomic background refresh from GitHub
├─ reference/
│  ├─ original_web_mvp.html      Original user-uploaded MVP, kept for reference
│  └─ original_leaflet_dashboard.html  Original advanced dashboard reference
├─ tests/test_api.py             Backend integration tests
├─ start_windows.bat
├─ start_linux_mac.sh
├─ .env.example
└─ requirements.txt
```

لإعادة بناء قاعدة البيانات من CSV الحالي *والسيرفر متوقف*:

```bash
python -m scripts.build_db --csv data/africa_fires_cleaned.csv --db data/fires.sqlite
```

للتأكد من نجاح الباك إند (يشمل ستة اختبارات):

```bash
AUTO_SYNC=0 python -m pytest -q
```

على Windows لتشغيل الاختبارات: `set AUTO_SYNC=0` ثم `python -m pytest -q` (يحتاج pytest لو مش مثبت: `python -m pip install pytest httpx`).

## ما معنى "جاهز" هنا، وما الذي يلزم لو أردت موقعًا عامًا على الإنترنت؟

**جاهز محليًا:** الموقع يعمل كـ Web App على جهازك، ببيانات حقيقية، وباك إند وفلترة وخريطة وتسجيل حسابات وحفظ مناطق. لم أنشره على سيرفر عام، ولا أستطيع التأكيد أن تحديث GitHub يعمل على بيئة الاستضافة قبل توفير الاستضافة والتحقق منها.

**قبل فتحه للجمهور:** يحتاج استضافة مستمرة، دومين، HTTPS، و`COOKIE_SECURE=1`، وإدارة أسرار ونسخ احتياطية وقاعدة بيانات دائمة وجدار حماية/معدلات استخدام. الحسابات الحالية Self-service؛ لا يوجد تحقق رسمي من مستندات الشركة، ولا دفع إلكتروني أو استعادة كلمات مرور بالبريد. الشات بوت غير موجود كما طلبت.

**ملاحظة GitHub:** قاعدة البيانات المحلية `fires.sqlite` أكبر من الحد الأقصى المعتاد لملف واحد في GitHub (100MB)، ولذلك `.gitignore` يمنع رفعها افتراضيًا. عند نشر الكود يمكن إعادة بنائها على السيرفر من CSV. **لا ترفع بيانات المستخدمين `users.sqlite` إلى مستودع عام.**

## المراجع الفنية ومصدر البيانات

- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/
- Repo الخاص بالفريق: https://github.com/Eman14215/africa_fires_data
- Natural Earth: https://www.naturalearthdata.com/ — حدود دول منخفضة الدقة، بيانات عامة Public Domain. الحدود تم الحصول عليها من حزمة بيانات Natural Earth Low Resolution مضمنة مع pyogrio، وتم تصديرها إلى GeoJSON لتشغيل المشروع دون geopandas.

