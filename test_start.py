import seedvis_app
import threading

app = seedvis_app.SeedvisApp()

def simulate():
    print("Simulating...")
    try:
        app._seed_claimed_products = [{"item_id": 12345, "name": "Test", "_status": "pending"}]
        app._seed_apikey_input.insert(0, "test_key")
        app._seed_start()
        print("Start called successfully")
    except Exception as e:
        print("Error:", e)
    app.after(3000, app.destroy)

app.after(500, simulate)
app.mainloop()
