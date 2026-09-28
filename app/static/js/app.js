/* Comportamentos globais do framework (§35.11, §37.14).
   Customizações do projeto devem ir em static/js/projeto.js. */
(function () {
    "use strict";

    /* --- Máscaras (§35.9): qualquer campo com data-mask --- */
    function aplicarMascaras(raiz) {
        if (typeof Inputmask === "undefined") return;
        (raiz || document).querySelectorAll("[data-mask]").forEach(function (el) {
            if (el.dataset.mascarado === "1") return;
            var mascara = el.dataset.mask;
            if (mascara === "moeda") {
                Inputmask({
                    alias: "numeric", groupSeparator: ".", radixPoint: ",",
                    digits: 2, digitsOptional: false, autoGroup: true,
                    rightAlign: true, allowMinus: false
                }).mask(el);
            } else {
                Inputmask({ mask: mascara }).mask(el);
            }
            el.dataset.mascarado = "1";
        });
    }

    /* --- Confirmação antes de excluir (§35.11) --- */
    document.addEventListener("submit", function (evento) {
        var alvo = evento.target.closest("[data-confirm]");
        if (!alvo || alvo.dataset.confirmado === "1") return;
        evento.preventDefault();
        var mensagem = alvo.dataset.confirm || "Confirma a operação?";
        if (typeof Swal === "undefined") {
            if (window.confirm(mensagem)) { alvo.dataset.confirmado = "1"; alvo.submit(); }
            return;
        }
        Swal.fire({
            title: "Confirmar", text: mensagem, icon: "warning",
            showCancelButton: true, confirmButtonText: "Sim, continuar",
            cancelButtonText: "Cancelar", reverseButtons: true,
            confirmButtonColor: "#dc3545"
        }).then(function (resultado) {
            if (resultado.isConfirmed) { alvo.dataset.confirmado = "1"; alvo.submit(); }
        });
    }, true);

    /* --- Loading no envio de formulários (§35.11) --- */
    document.addEventListener("submit", function (evento) {
        var form = evento.target;
        if (form.hasAttribute("data-confirm") && form.dataset.confirmado !== "1") return;
        form.querySelectorAll("button[type=submit]").forEach(function (botao) {
            botao.disabled = true;
            botao.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1"></span>Aguarde...';
        });
    });

    /* --- Notificações no canto superior direito (§37.14) --- */
    window.notificar = function (mensagem, tipo) {
        var cores = { sucesso: "success", erro: "danger", aviso: "warning", info: "info" };
        var cor = cores[tipo] || "info";
        var area = document.getElementById("area-toasts");
        if (!area) return;
        var toast = document.createElement("div");
        toast.className = "toast align-items-center text-bg-" + cor + " border-0";
        toast.setAttribute("role", "alert");
        toast.innerHTML =
            '<div class="d-flex"><div class="toast-body">' + mensagem + "</div>" +
            '<button type="button" class="btn-close btn-close-white me-2 m-auto"' +
            ' data-bs-dismiss="toast"></button></div>';
        area.appendChild(toast);
        new bootstrap.Toast(toast, { delay: 4000 }).show();
        toast.addEventListener("hidden.bs.toast", function () { toast.remove(); });
    };

    document.addEventListener("DOMContentLoaded", function () {
        aplicarMascaras();
        /* Conteúdo trocado pelo HTMX também recebe as máscaras. */
        document.body.addEventListener("htmx:afterSwap", function (e) {
            aplicarMascaras(e.target);
        });
    });

    window.aplicarMascaras = aplicarMascaras;
})();
