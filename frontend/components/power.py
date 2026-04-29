import streamlit as st


def power(data):
    pw = data["power_now"]
    pw_pct = int(pw / data["power_max"] * 100)
    pw_color = "#e07b20" if pw_pct > 80 else "#0077cc"

    st.markdown(f"""
    <div class="card power-card">
      <div class="card-label">현재 전력</div>
      <div>
        <span class="card-value" style="font-size:2rem;color:{pw_color}">
          {pw}
        </span>
        <span class="card-unit">kW</span>
      </div>
      <div class="power-bar-bg">
        <div class="power-bar-fill" style="width:{pw_pct}%;background:linear-gradient(90deg,{pw_color}99,{pw_color});"></div>
      </div>
      <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#6b8299;margin-top:0.3rem;">
        {pw_pct}% / 정격 {int(data['power_max'])}kW
      </div>
    </div>
    """, unsafe_allow_html=True)