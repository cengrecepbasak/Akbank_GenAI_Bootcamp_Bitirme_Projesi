from flask import Flask, render_template, request, jsonify
import chromadb
import google.generativeai as genai
import os
from dotenv import load_dotenv
import numpy as np
import re
import hashlib
import requests
import pandas as pd
import json
import ast

# .env dosyasını yükle - Çevresel değişkenleri yüklemek için
load_dotenv()

# Flask uygulamasını başlat
app = Flask(__name__)

# API key'i environment variable'dan al - Güvenli anahtar yönetimi
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# MODEL KONFİGÜRASYONU - GÜNCEL VERSİYON
genai_model = None  # Model değişkenini başlat

# Eğer API anahtarı varsa modeli yapılandır
if GEMINI_API_KEY:
    try:
        # Google Generative AI'yı API anahtarı ile yapılandır
        genai.configure(api_key=GEMINI_API_KEY)
        
        # EN GÜNCEL VE ÇALIŞAN MODELLER - Kullanılabilecek model listesi
        working_models = [
            'gemini-2.0-flash',
            'gemini-2.0-flash-001',
            'gemini-2.5-flash', 
            'gemini-flash-latest',
            'gemini-pro-latest',
            'gemini-1.5-flash'
        ]
        
        # Mevcut modelleri deneyerek çalışan birini bul
        for model_name in working_models:
            try:
                print(f"🔧 {model_name} deneniyor...")
                # Modeli oluştur
                genai_model = genai.GenerativeModel(model_name)
                # Modelin çalıştığını test et
                test_response = genai_model.generate_content("Merhaba")
                print(f"✅ {model_name} modeli başarıyla yüklendi!")
                break  # Çalışan model bulundu, döngüden çık
            except Exception as e:
                print(f"❌ {model_name} çalışmadı: {e}")
                continue
                
        # Hiçbir model çalışmazsa fallback moduna geç
        if not genai_model:
            print("🚫 Hiçbir model çalışmadı, fallback moduna geçiliyor")
            
    except Exception as e:
        print(f"❌ Model yükleme hatası: {e}")
        genai_model = None
else:
    print("⚠️  GEMINI_API_KEY bulunamadı. Fallback modunda çalışıyor.")

# Basit embedding fonksiyonu - Vektör temsilleri oluşturur
def simple_embedding(text, dimensions=384):
    # Metni kelimelere ayır ve küçük harfe çevir
    words = re.findall(r'\w+', text.lower())
    # Sıfırlarla dolu vektör başlat
    vector = np.zeros(dimensions)
    
    # Her kelime için hash tabanlı embedding oluştur
    for word in words:
        # Kelimenin MD5 hash'ini hesapla
        hash_val = int(hashlib.md5(word.encode()).hexdigest(), 16)
        # Vektördeki pozisyonu belirle
        pos = hash_val % dimensions
        # Hash değerine göre pozitif/negatif ağırlık ata
        vector[pos] += 1 if hash_val % 2 == 0 else -1
    
    # Vektörü normalize et (birim vektör haline getir)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    
    # Listeye çevirerek döndür
    return vector.tolist()

# ChromaDB istemcisi - Bellek içi vektör veritabanı
client = chromadb.Client()
# Koleksiyon oluştur - Belgeleri saklayacak konteyner
collection = client.create_collection(name="turkish_wiki_qa")

def load_comprehensive_dataset():
    """Kapsamlı ve zengin dataset - Önceden tanımlanmış soru-cevap çiftleri"""
    print("📥 Kapsamlı dataset yükleniyor...")
    
    # Önceden tanımlanmış soru-cevap çiftleri
    comprehensive_docs = [
        # ATATÜRK İLE İLGİLİ SORULAR
        "S: Mustafa Kemal Atatürk kimdir? - C: Mustafa Kemal Atatürk, Türkiye Cumhuriyeti'nin kurucusu ve ilk cumhurbaşkanıdır. 1881 yılında Selanik'te doğmuş, 1919'da Samsun'a çıkarak Kurtuluş Savaşı'nı başlatmış, 1923'te cumhuriyeti ilan etmiş ve modern Türkiye'yi kurmuştur. Askeri deha, devlet adamı ve reformist bir liderdir.",
        "S: Atatürk kimdir? - C: Atatürk, Türkiye Cumhuriyeti'nin kurucusu ve modern Türkiye'nin mimarıdır. Laik, demokratik ve bağımsız Türkiye'yi kurmuştur. 1881-1938 yılları arasında yaşamıştır.",
        # ... diğer dokümanlar
    ]
    
    print(f"✅ {len(comprehensive_docs)} kapsamlı soru-cevap çifti yüklenmiş")
    return comprehensive_docs

# Veritabanını başlat
print("📚 Türkçe QA veritabanı oluşturuluyor...")
sample_docs = load_comprehensive_dataset()

# Embedding'leri oluştur ve ChromaDB'ye kaydet
print(f"🔧 {len(sample_docs)} doküman için embedding'ler oluşturuluyor...")

# Her doküman için embedding vektörleri oluştur
embeddings = [simple_embedding(doc) for doc in sample_docs]
# Embedding'leri, dokümanları ve ID'leri koleksiyona ekle
collection.add(
    embeddings=embeddings,
    documents=sample_docs,
    ids=[f"doc_{i}" for i in range(len(sample_docs))]
)
print("✅ QA veritabanı başarıyla oluşturuldu")

# Önemli dokümanları göster - Debug amaçlı
print("📖 Önemli doküman örnekleri:")
important_keywords = ['Atatürk', 'Theodoros', 'Python', 'Niğbolu']
for i, doc in enumerate(sample_docs):
    if any(keyword.lower() in doc.lower() for keyword in important_keywords):
        print(f"  {i+1}. {doc[:80]}...")

def retrieve_documents(query, n_results=3):
    """Benzer dokümanları getir - Vektör benzerlik araması"""
    try:
        # Sorgu için embedding oluştur
        query_embedding = simple_embedding(query)
        # ChromaDB'de benzerlik araması yap
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        # Sonuçlardan dokümanları döndür
        return results['documents'][0] if results['documents'] else []
    except Exception as e:
        print(f"❌ Retrieval hatası: {e}")
        return []

def smart_fallback_answer(query, context_docs):
    """Akıllı fallback cevap sistemi - Gemini çalışmazsa kullanılır"""
    if not context_docs:
        return "Üzgünüm, bu konuda yeterli bilgi bulunamadı."
    
    # En iyi eşleşmeyi bul - Skorlama sistemi
    best_match = None
    max_score = 0
    
    for doc in context_docs:
        score = 0
        # Sorgudaki anlamlı kelimeleri al (2 karakterden uzun)
        query_words = [word for word in query.lower().split() if len(word) > 2]
        
        # Anahtar kelime eşleştirme - Benzerlik skoru hesapla
        for word in query_words:
            if word in doc.lower():
                if len(word) > 4:  # Uzun kelimeler daha önemli
                    score += 3
                else:
                    score += 1
        
        # Tam soru eşleşmesi (en yüksek puan)
        if "S: " + query in doc or "S: " + query + "?" in doc:
            score += 10
            
        if score > max_score:
            max_score = score
            best_match = doc
    
    # Cevabı çıkar - Formatı parse et
    if best_match:
        if "C: " in best_match:
            return best_match.split("C: ")[1]
        elif " - C: " in best_match:
            return best_match.split(" - C: ")[1]
        else:
            return best_match
    
    return context_docs[0]

def generate_answer(query, context_docs):
    """Cevap oluştur - GELİŞMİŞ SİSTEM: Gemini API + Fallback"""
    if not context_docs:
        return "Üzgünüm, bu konuda yeterli bilgi bulunamadı. Lütfen sorunuzu farklı şekilde ifade etmeyi deneyin."
    
    print(f"🔍 İlgili dokümanlar: {[doc[:60] + '...' for doc in context_docs]}")
    
    # 1. GEMINI API DENEME - Öncelikli yöntem
    if genai_model:
        try:
            # Bağlam bilgilerini birleştir
            context = "\n".join(context_docs)
            # Prompt oluştur
            prompt = f"""Aşağıdaki bağlam bilgilerini kullanarak kullanıcının sorusunu kapsamlı ve doğru bir şekilde Türkçe olarak cevaplayın.

BAĞLAM BİLGİLERİ:
{context}

KULLANICI SORUSU: {query}

KAPSAMLI VE DOĞRU CEVAP:"""
            
            # Gemini'den cevap oluştur
            response = genai_model.generate_content(prompt)
            answer = response.text.strip()
            print(f"🤖 Gemini cevabı: {answer[:100]}...")
            return answer
            
        except Exception as e:
            print(f"❌ Gemini hatası, fallback kullanılıyor: {e}")
    
    # 2. AKILLI FALLBACK - Yedek sistem
    print("🔄 Akıllı fallback sistemi kullanılıyor...")
    return smart_fallback_answer(query, context_docs)

@app.route('/')
def home():
    """Ana sayfa - HTML template'i render et"""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Chat endpoint'i - Kullanıcı mesajını işle ve cevap döndür"""
    user_message = request.json['message']
    print(f"💬 Kullanıcı sorusu: {user_message}")
    
    try:
        # İlgili dokümanları getir
        relevant_docs = retrieve_documents(user_message)
        print(f"📄 Bulunan ilgili doküman sayısı: {len(relevant_docs)}")
        
        # Cevap oluştur
        bot_response = generate_answer(user_message, relevant_docs)
        
        # JSON response döndür
        return jsonify({
            'response': bot_response,
            'sources': relevant_docs[:2]  # İlk 2 kaynağı göster
        })
    except Exception as e:
        print(f"❌ Chat hatası: {e}")
        return jsonify({
            'response': 'Üzgünüm, şu anda bir hata oluştu. Lütfen daha sonra tekrar deneyin.',
            'sources': []
        })

@app.route('/health')
def health_check():
    """Sağlık kontrolü - Sistem durumunu göster"""
    return jsonify({
        'status': 'healthy',
        'gemini_configured': bool(genai_model),
        'qa_pairs_count': len(sample_docs),
        'model_active': 'Evet' if genai_model else 'Hayır (Fallback)'
    })

if __name__ == '__main__':
    # Uygulama başlatma bilgileri
    print("🚀 Türkçe QA Chatbot başlatılıyor...")
    print(f"🔑 API Key Durumu: {'✅ Var' if GEMINI_API_KEY else '❌ Yok'}")
    print(f"🤖 Model Durumu: {'✅ Aktif' if genai_model else '🔄 Fallback Modu'}")
    print(f"📚 Soru-cevap çifti sayısı: {len(sample_docs)}")
    print("🌐 Uygulama http://localhost:5000 adresinde çalışıyor")
    # Flask uygulamasını başlat
    app.run(debug=True, host='0.0.0.0', port=5000)