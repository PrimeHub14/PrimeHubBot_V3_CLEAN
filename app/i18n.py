TRANSLATIONS = {
    "en": {"welcome":"Welcome","store":"Prime Hub Store","shop":"Shop","search":"Search","wallet":"Wallet","orders":"Orders","rewards":"Rewards","vip":"VIP","wishlist":"Wishlist","recommend":"Recommendations","support":"Support","language":"Language","profile":"Profile","updates":"Updates","choose_language":"Choose your language","saved":"Language preference saved."},
    "pt": {"welcome":"Bem-vindo","store":"Prime Hub Store","shop":"Loja","search":"Pesquisar","wallet":"Carteira","orders":"Pedidos","rewards":"Recompensas","vip":"VIP","wishlist":"Favoritos","recommend":"Recomendações","support":"Suporte","language":"Idioma","profile":"Perfil","updates":"Atualizações","choose_language":"Escolha seu idioma","saved":"Preferência de idioma salva."},
    "hi": {"welcome":"स्वागत है","store":"Prime Hub Store","shop":"शॉप","search":"खोजें","wallet":"वॉलेट","orders":"ऑर्डर","rewards":"रिवॉर्ड्स","vip":"VIP","wishlist":"विशलिस्ट","recommend":"सुझाव","support":"सहायता","language":"भाषा","profile":"प्रोफ़ाइल","updates":"अपडेट्स","choose_language":"अपनी भाषा चुनें","saved":"भाषा सेटिंग सेव हो गई।"},
    "es": {"welcome":"Bienvenido","store":"Prime Hub Store","shop":"Tienda","search":"Buscar","wallet":"Cartera","orders":"Pedidos","rewards":"Recompensas","vip":"VIP","wishlist":"Favoritos","recommend":"Recomendaciones","support":"Soporte","language":"Idioma","profile":"Perfil","updates":"Novedades","choose_language":"Elige tu idioma","saved":"Preferencia de idioma guardada."},
    "ar": {"welcome":"مرحباً","store":"متجر Prime Hub","shop":"المتجر","search":"بحث","wallet":"المحفظة","orders":"الطلبات","rewards":"المكافآت","vip":"VIP","wishlist":"المفضلة","recommend":"التوصيات","support":"الدعم","language":"اللغة","profile":"الملف الشخصي","updates":"التحديثات","choose_language":"اختر لغتك","saved":"تم حفظ اللغة."},
}
LANGUAGE_NAMES = {"en":"🇬🇧 English","pt":"🇧🇷 Português","hi":"🇮🇳 हिन्दी","es":"🇪🇸 Español","ar":"🇸🇦 العربية"}

def tr(lang: str | None, key: str) -> str:
    lang = lang if lang in TRANSLATIONS else "en"
    return TRANSLATIONS[lang].get(key, TRANSLATIONS["en"].get(key, key))
