import streamlit as st
import plotly.graph_objects as go


def temp_chart(data):
    fig = go.Figure()

    fig.add_hrect(
        y0=-16,
        y1=-13,
        fillcolor="rgba(255,107,107,0.08)",
        line_width=0,
        annotation_text="경보 구간",
        annotation_position="top right",
        annotation_font=dict(size=9, color="#ff6b6b"),
    )

    fig.add_hline(
        y=-18,
        line_dash="dot",
        line_color="#c8d9ec",
        annotation_text="-18°C 목표",
        annotation_position="bottom right",
        annotation_font=dict(size=9, color="#6b8299"),
    )

    fig.add_trace(go.Scatter(
        x=data["times"],
        y=data["temps"],
        mode="lines",
        line=dict(color="#0077cc", width=2.5, shape="spline"),
        fill="tozeroy",
        fillcolor="rgba(0,119,204,0.08)",
        hovertemplate="%{x|%H:%M}<br><b>%{y}°C</b><extra></extra>",
        showlegend=False,
    ))

    fig.add_trace(go.Scatter(
        x=[data["times"][-1]],
        y=[data["temps"][-1]],
        mode="markers",
        marker=dict(color="#0077cc", size=9, line=dict(color="#ffffff", width=2)),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=10, r=10, t=10, b=10),
        height=260,
        showlegend=False,
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            tickmode="array",
            tickvals=[
                data["times"][0],
                data["times"][6],
                data["times"][12],
                data["times"][18],
            ],
            ticktext=["00시", "06시", "12시", "18시"],
            tickfont=dict(size=9, color="#6b8299"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(200,217,236,0.7)",
            zeroline=False,
            showline=False,
            ticks="",
            tickmode="array",
            tickvals=[-20, -15, -10, -5],
            ticktext=["-20°", "-15°", "-10°", "-5°"],
            tickfont=dict(size=9, color="#6b8299"),
            range=[-21, -4],
        ),
    )

    with st.container(border=True, key="temp-chart-card"):
        st.markdown("""
        <div class="card-label">24시간 온도 추이</div>
        """, unsafe_allow_html=True)

        st.plotly_chart(
            fig,
            width="stretch",
            config={"displayModeBar": False},
        )