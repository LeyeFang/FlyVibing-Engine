# UI 展开图速查（自动生成）

> 源：`Doc/Dev/ui_map.json`。修改 JSON 后运行 `python Utils/Dev/test_map.py ui render`，不要手改本文件。

## 控件树

```text
editor.shell [screen] owner=UIManager  actions=editor.quit
  - editor.status_bar [status] owner=UIManager  when=editor.workspace actions=sim.state
  - editor.menu.file [menu] owner=UIManager  when=editor.workspace actions=project.open,project.save,project.export
  - editor.menu.view [menu] owner=UIManager  when=editor.workspace actions=ui.panels,ui.panel,view.set_grid,view.set_mode
  - editor.menu.extensions [menu] owner=ExtensionManager  when=editor.workspace actions=extension.list,extension.enable,extension.disable
  - editor.panel.scene [panel] owner=ScenePanel  when=panel.scene.visible actions=entity.list,entity.get,entity.add,entity.delete,entity.rename,entity.visible,scene.list,scene.switch,scene.create,scene.save,scene.load,sim.play,sim.stop
    - editor.scene.entity_tree [tree] owner=SceneBrowserController  when=scene.loaded,panel.scene.visible actions=entity.list,entity.get,entity.visible,selection.set,selection.clear,entity.reparent,entity.rename,entity.delete
      - editor.scene.context_menu [popup] owner=ScenePanel  when=scene.context_menu.open actions=entity.add,entity.rename,entity.delete,entity.reparent
    - editor.scene.inspector [inspector] owner=SceneBrowserController  when=scene.loaded,panel.scene.visible actions=camera.get,camera.set,component.types,component.list,component.get,component.add,component.remove,component.set,entity.get,entity.visible,entity.transform,selection.get
  - editor.panel.node_editor [panel] owner=NodeEditorPanel  when=panel.node_editor.visible actions=graph.list,graph.types,graph.add,graph.link,graph.set_props,graph.set_description,graph.fit,graph.export,graph.import,graph.validate.start,graph.validate.state,graph.validate.report,graph.validate.cancel
    - editor.node_editor.find_window [dialog] owner=NodeEditorPanel  when=find.open
    - editor.node_editor.groups_window [dialog] owner=NodeEditorPanel  when=groups.open
    - editor.node_editor.add_menu [menu] owner=NodeEditorPanel  when=add_menu.open actions=graph.types,graph.add
    - editor.node_editor.node_card [card] owner=NodeEditorWidgets  when=panel.node_editor.visible actions=graph.set_props,graph.set_description
    - editor.node_editor.validate_dialog [dialog] owner=GraphValidationService  when=validate.open actions=graph.validate.start,graph.validate.state,graph.validate.report,graph.validate.cancel
  - editor.panel.resources [panel] owner=ResourcePanel  when=panel.resources.visible actions=resource.list,resource.find
    - editor.resources.asset_list [list] owner=ResourceBrowserController  when=panel.resources.visible actions=resource.material.get
  - editor.panel.settings [panel] owner=SettingsPanel  when=panel.settings.visible actions=settings.get,settings.set
    - editor.settings.common [page] owner=SettingsPanel  when=panel.settings.visible actions=settings.get,settings.set
    - editor.settings.export [page] owner=SettingsPanel  when=panel.settings.visible actions=settings.get,settings.set
  - dialog.file [dialog] owner=FileDialog  when=dialog.file.open
  - extension.window [window] owner=ExtensionUI  when=extension.window.visible
```

## 控件

| id | kind | owner | visible_when | actions | tests | scenarios | source |
|---|---|---|---|---|---|---|---|
| `editor.shell` | `screen` | `UIManager` | - | editor.quit | editor.action_contract, editor.live_command_server | panels_smoke | `Application/Editor/UI/UIManager.py` |
| `editor.status_bar` | `status` | `UIManager` | editor.workspace | sim.state | editor.live_command_server | panels_smoke | `Application/Editor/UI/UIManager.py` |
| `editor.menu.file` | `menu` | `UIManager` | editor.workspace | project.open, project.save, project.export | editor.action_contract, editor.export_game_bundle | menu_smoke | `Application/Editor/UI/UIManager.py` |
| `editor.menu.view` | `menu` | `UIManager` | editor.workspace | ui.panels, ui.panel, view.set_grid, view.set_mode | editor.action_contract, editor.live_command_server | menu_smoke | `Application/Editor/UI/UIManager.py` |
| `editor.menu.extensions` | `menu` | `ExtensionManager` | editor.workspace | extension.list, extension.enable, extension.disable | extensions.extension_manager, extensions.extension_ui | menu_smoke | `Application/Editor/Extensions/ExtensionMenu.py` |
| `editor.panel.scene` | `panel` | `ScenePanel` | panel.scene.visible | entity.list, entity.get, entity.add, entity.delete, entity.rename, entity.visible, scene.list, scene.switch, scene.create, scene.save, scene.load, sim.play, sim.stop | editor.scene_panel_interactions, editor.action_contract | panels_smoke | `Application/Editor/UI/panels/ScenePanel.py` |
| `editor.scene.entity_tree` | `tree` | `SceneBrowserController` | scene.loaded, panel.scene.visible | entity.list, entity.get, entity.visible, selection.set, selection.clear, entity.reparent, entity.rename, entity.delete | editor.scene_panel_interactions, editor.action_contract | panels_smoke | `Application/Editor/UI/controllers/SceneBrowserController.py` |
| `editor.scene.inspector` | `inspector` | `SceneBrowserController` | scene.loaded, panel.scene.visible | camera.get, camera.set, component.types, component.list, component.get, component.add, component.remove, component.set, entity.get, entity.visible, entity.transform, selection.get | editor.scene_panel_interactions, core.component_clamps | panels_smoke | `Application/Editor/UI/controllers/SceneBrowserController.py` |
| `editor.scene.context_menu` | `popup` | `ScenePanel` | scene.context_menu.open | entity.add, entity.rename, entity.delete, entity.reparent | editor.scene_panel_interactions | panels_smoke | `Application/Editor/UI/panels/ScenePanel.py` |
| `editor.panel.node_editor` | `panel` | `NodeEditorPanel` | panel.node_editor.visible | graph.list, graph.types, graph.add, graph.link, graph.set_props, graph.set_description, graph.fit, graph.export, graph.import, graph.validate.start, graph.validate.state, graph.validate.report, graph.validate.cancel | nodegraph.node_editor_mcp, editor.examples_catalog | node_editor_smoke, node_editor_clip_smoke, node_editor_find, node_groups_smoke | `Application/Editor/UI/panels/node_editor/panel.py` |
| `editor.node_editor.find_window` | `dialog` | `NodeEditorPanel` | find.open | - | - | node_editor_find | `Application/Editor/UI/panels/node_editor/panel.py` |
| `editor.node_editor.groups_window` | `dialog` | `NodeEditorPanel` | groups.open | - | - | node_groups_smoke | `Application/Editor/UI/panels/node_editor/panel.py` |
| `editor.node_editor.add_menu` | `menu` | `NodeEditorPanel` | add_menu.open | graph.types, graph.add | nodegraph.node_pack, editor.examples_catalog | node_editor_smoke | `Application/Editor/UI/panels/node_editor/panel.py` |
| `editor.node_editor.node_card` | `card` | `NodeEditorWidgets` | panel.node_editor.visible | graph.set_props, graph.set_description | nodegraph.node_pack, nodegraph.node_editor_mcp | node_editor_smoke | `Application/Editor/UI/panels/node_editor/widgets/core.py` |
| `editor.node_editor.validate_dialog` | `dialog` | `GraphValidationService` | validate.open | graph.validate.start, graph.validate.state, graph.validate.report, graph.validate.cancel | nodegraph.graph_validation | node_editor_smoke | `Application/Core/NodeGraph/validation/service.py` |
| `editor.panel.resources` | `panel` | `ResourcePanel` | panel.resources.visible | resource.list, resource.find | editor.live_command_server | panels_smoke | `Application/Editor/UI/panels/ResourcePanel.py` |
| `editor.resources.asset_list` | `list` | `ResourceBrowserController` | panel.resources.visible | resource.material.get | editor.live_command_server | panels_smoke | `Application/Editor/UI/controllers/ResourceBrowserController.py` |
| `editor.panel.settings` | `panel` | `SettingsPanel` | panel.settings.visible | settings.get, settings.set | editor.editor_settings, editor.i18n_coverage | panels_smoke | `Application/Editor/UI/panels/SettingsPanel.py` |
| `editor.settings.common` | `page` | `SettingsPanel` | panel.settings.visible | settings.get, settings.set | editor.editor_settings, editor.i18n_coverage | panels_smoke | `Application/Editor/UI/panels/SettingsPanel.py` |
| `editor.settings.export` | `page` | `SettingsPanel` | panel.settings.visible | settings.get, settings.set | editor.editor_settings, editor.pie_settings | panels_smoke | `Application/Editor/UI/panels/SettingsPanel.py` |
| `dialog.file` | `dialog` | `FileDialog` | dialog.file.open | - | editor.utils_layout | menu_smoke | `Application/Editor/UI/FileDialog.py` |
| `extension.window` | `window` | `ExtensionUI` | extension.window.visible | - | extensions.extension_ui, extensions.virtual_panel | - | `Application/Editor/Extensions/ExtensionUI.py` |
