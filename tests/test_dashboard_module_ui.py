from app.services.dashboard_module_ui import enhance_dashboard_module_ui


def test_dashboard_module_navigation_replaces_flat_menu_and_adds_context():
    html = '''
    <style></style>
    <nav>
      <button class="navbtn active" data-page="overview">Visão geral</button>
      <button class="navbtn" data-page="events">Eventos</button>
      <button class="navbtn" data-page="manager">Gerencial</button>
      <button class="navbtn" data-page="inventory">Estoque</button>
      <button class="navbtn" data-page="telegram">Telegram</button>
      <button class="navbtn" id="logoutBtn">Sair</button>
    </nav>
    <main>
      <h2>Módulos liberados</h2>
      <section class="page" id="page-inventory"></section>
    </main>
    <script>function render(){}</script>
    </body>
    '''

    rendered = enhance_dashboard_module_ui(html)

    assert "MÓDULOS" in rendered
    assert 'id="moduleNav"' in rendered
    assert "Seus módulos" in rendered
    assert 'id="page-module"' in rendered
    assert "Fábrica de Ração · Estoque" in rendered
    assert 'data-page="inventory">Estoque</button>' not in rendered
    assert "permission_aware" not in rendered
