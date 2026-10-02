/* Isnad database — sign-in */

const $ = (id) => document.getElementById(id);

function showError(message) {
  $("login-error").textContent = message;
  $("login-error").hidden = false;
}

async function login(event) {
  event.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  if (!username || !password) {
    showError("أدخل اسم المستخدم وكلمة المرور");
    return;
  }

  $("login-btn").disabled = true;
  $("login-btn").classList.add("loading");
  $("login-error").hidden = true;

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (res.ok) {
      window.location.href = "/";
      return;
    }
    const message =
      res.status === 429
        ? "محاولات كثيرة، حاول مرة أخرى بعد ربع ساعة"
        : (await res.json().catch(() => ({}))).detail || `خطأ (${res.status})`;
    throw new Error(message);
  } catch (err) {
    showError(err.message);
    $("password").value = "";
    $("password").focus();
  } finally {
    $("login-btn").disabled = false;
    $("login-btn").classList.remove("loading");
  }
}

function setupPasswordToggles() {
  document.querySelectorAll("[data-toggle-password]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = $(btn.dataset.togglePassword);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      const label = show ? "إخفاء كلمة المرور" : "إظهار كلمة المرور";
      btn.setAttribute("aria-label", label);
      btn.title = label;
      btn.classList.toggle("active", show);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("login-form").addEventListener("submit", login);
  setupPasswordToggles();
});
